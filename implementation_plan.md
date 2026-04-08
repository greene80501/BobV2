# Bob V2 — Remaining Implementation Work

Everything listed here is **not yet working end-to-end**. Items already implemented have been removed.

---

## 1. Terminal UI & Prompt Experience

**1.1 Status line hooks**
`bob/hooks/runner.py` exists but its output is never surfaced in the UI. Wire:
- After each turn, run configured `post_turn` hooks from `session.config.hooks`.
- Display stdout of hooks in a dim status line below the response.
- The runner already has `run_hooks(event, config)` — call it after `TurnEndedEvent` in the
  `_consume_events` loop and `_p()` any non-empty stdout.

**1.2 Image attachment in TUI** [data done — `ImageUserInput` exists in protocol]
`view_image.py` tool exists but there is no way to attach an image from the prompt.
Implement `@image` syntax:
- In the prompt completer, detect `@` prefix and offer file path completion for
  `.png`, `.jpg`, `.gif`, `.webp` extensions.
- When input is submitted, scan for `@/path/to/image.png` tokens.
- Convert matched paths to `ImageUserInput` items passed to `UserTurnOp`.

---

## 2. Tools — Missing or Incomplete

**2.1 Cron/Schedule tools**
No scheduling system exists. Build:
- `ScheduleCronTool(cron_expr, task_description)` → saves schedule to
  `~/.bob/schedules.db`, returns schedule_id.
- `RemoteTriggerTool(schedule_id)` → manually fires a scheduled task.
- A background runner (separate process or thread) that executes due tasks and
  submits them as new `UserTurnOp` to a session.

**2.2 'review' agent template** [partial — explore/plan/verify/write exist in agent_templates.py]
`agent_templates.py` has four templates but is missing `review`. Add:
- `review` — code reviewer, reads PR diff/file changes, produces structured review
  comments. Allowed tools: `read_file`, `glob_files`, `grep_files`, `shell` (read-only
  git commands only). System prompt: focused on reviewing diffs and flagging issues.

---

## 3. Agent & Multi-Agent

**3.1 Agent memory snapshots**
No mechanism to capture what a sub-agent learned between runs. Build:
- At sub-agent shutdown, extract a "memory snapshot" (summary of findings, key facts,
  files modified) from the agent's final context via a quick model call.
- Store snapshot keyed by agent name + session in `~/.bob/agent_memory.db`.
- On next spawn with same agent name, inject prior snapshot into context.

---

## 4. Performance

**4.1 Session pre-warm**
First response is cold (TCP + TLS + model warmup). Fix:
- In `session.start()`, fire a background task that sends a minimal keepalive request
  to the API endpoint immediately on startup.
- Don't await it — just let it run so the connection is warm by the time the user
  submits their first message.

**4.2 Frame rate limiting**
Fast streaming can flood the terminal. Fix:
- In the TUI's event consumption loop, track the last render time.
- Batch `TextDeltaEvent` chunks that arrive within 16ms (60fps) and render them
  together in one `print()` call.
- Use `asyncio.sleep(0)` between batches to yield to the event loop.

---

## 5. Security & Sandbox

**5.1 Network approval flow**
`network_access: bool` in config is all-or-nothing. Build per-request approval:
- Intercept outbound HTTP calls from `web_fetch` and `web_search` tools.
- Check domain against an approved-domains list in config.
- If not approved, emit `NetworkApprovalRequestedEvent` and pause — same flow as
  `ExecApprovalRequestedEvent`.
- User can approve once, approve always, or deny.

**5.2 Command canonicalization in approval**
`_format_command` in `interface.py` normalizes for display only. The approval system
sees the raw command. Fix:
- In `exec_policy.py` / `needs_approval()`, normalize the command before matching
  trusted patterns (unwrap `cmd /c`, `powershell -Command`, resolve `./` paths).
- This prevents approval bypasses via shell metacharacter wrapping.

~~**5.3 macOS Seatbelt policy files**~~ ✅ Already fully implemented in `sandbox/macos.py`.

~~**5.4 Linux bubblewrap + Landlock**~~ ✅ Already fully implemented in `sandbox/linux.py`.

**5.5 Shell escalation detection**
No detection of sandbox-escape attempts. Add to `exec_policy.py`:
- Reject or require explicit approval for: `sudo`, `su`, `chroot`, `nsenter`,
  `unshare`, `ptrace`, `LD_PRELOAD`, shell metacharacters in trusted-command paths.
- Log all escalation attempts.

---

## 6. Session & Memory

**6.1 Turn diff tracking**
No record of which files changed in each turn. Build:
- Before each turn, snapshot a hash of all files in `session.cwd` (or track via
  `write_file`/`edit_file`/`apply_patch` calls).
- After the turn, compute which files changed.
- Store as a per-turn diff summary in the analytics DB.
- Surface in `/stats` and the turn status line.

---

## 7. Integrations

**7.1 Web search end-to-end verification**
`web_search.py` exists and is registered. Verify and fix:
- Confirm DuckDuckGo API calls work without a key in a live session.
- Add a fallback (SerpAPI or Brave Search) when DDG is rate-limited.
- Wire `web_search_mode` config field to conditionally register the tool
  (currently it is always registered regardless of the config flag).

---

## 8. Quality of Life

**8.1 Error messages with file:line context**
Errors are plain strings. Improve:
- In `StreamErrorEvent` and `ErrorEvent` handlers, parse Python tracebacks if present.
- Highlight file paths and line numbers using `rich.traceback.Traceback`.
- For tool errors, include the tool name and input in the display.

---

## Priority Order (highest impact first)

1. ~~**§5.2 Command canonicalization**~~ ✅ done — `_canonicalize_command()` in `turn.py`
2. ~~**§5.5 Shell escalation detection**~~ ✅ done — `detect_escalation()` in `turn.py`
3. ~~**§2.1 Cron/Schedule tools**~~ ✅ done — `cron_tools.py` with `schedule_cron` + `remote_trigger`, registered in session
4. ~~**§2.2 'review' agent template**~~ ✅ done — added to `agent_templates.py`
5. ~~**§3.1 Agent memory snapshots**~~ ✅ done — `agent_memory.py`, wired in `thread_manager.py`
6. ~~**§4.2 Frame rate limiting**~~ ✅ done — 16ms batch buffer in `interface.py`
7. ~~**§1.1 Status line hooks**~~ ✅ done — `post_turn` hooks wired in `TurnEndedEvent` handler
8. ~~**§7.1 Web search verification**~~ ✅ done — DDG fallback + config-gated registration
9. ~~**§8.1 Error messages with file:line**~~ ✅ done — `_render_error()` with Rich panel + regex highlights
10. ~~**§6.1 Turn diff tracking**~~ ✅ done — `_snapshot_dir`/`_diff_snapshot` in `turn.py`, stored in analytics DB
11. ~~**§1.2 Image attachment**~~ ✅ done — `_parse_at_images()` + `ImageUserInput` wiring in submit path
12. ~~**§4.1 Session pre-warm**~~ ✅ done — `_prewarm_connection()` fire-and-forget in `session.start()`
13. ~~**§5.1 Network approval flow**~~ ✅ done — `NetworkApprovalRequestedEvent` + TUI prompt wired in
14. ~~**§5.3 macOS Seatbelt**~~ ✅ already fully implemented in `sandbox/macos.py`
15. ~~**§5.4 Linux bubblewrap + Landlock**~~ ✅ already fully implemented in `sandbox/linux.py`

