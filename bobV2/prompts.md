  ---                                                                                                                                                                                                 
  1. Parallel research + synthesis (tests spawn_agent × 2, wait_agent, result combining)
                                                                                                                                                                                                      
  Spawn two agents in parallel: one that searches the web for recent Python async best practices (2024-2025), and one that reads our codebase to find everywhere we use asyncio. Then wait for both
  and write a short report on what we're doing well vs. what we should improve.

  This hits: spawn × 2, both running concurrently, wait_agent(["agent_1", "agent_2"]), parent synthesizing two result blobs.

  ---
  2. Mid-run course correction (tests assign_task interrupt)

  Spawn an agent to analyze all the Python files in bob/core/ and write a detailed summary of each one. After spawning it, wait about 10 seconds, then use assign_task to tell it "focus only on
  session.py and turn.py, skip the rest." Then wait for the result.

  This tests whether assign_task actually triggers a new turn mid-run and whether the agent changes direction. You'll see it in the TUI spinner label updating.

  ---
  3. Worktree isolation + auto-merge (tests git worktree create/merge flow)

  Spawn an agent called "formatter" with this task: "Add a module-level docstring to bob/core/agents/registry.py, bob/core/agents/mailbox.py, and bob/core/agents/worktree.py. Each docstring should
  be one sentence describing what the module does." Then wait for it and check git log to confirm the squash commit landed.

  This is the first real write-to-files test. After it completes you should see a git log entry like agent(xxxx): merged result.

  ---
  4. Concurrent codebase + web (tests max parallelism, TUI panel with multiple agents running)

  I want to add streaming progress to our sub-agent TUI panel. Spawn three agents simultaneously: (1) "web_researcher" - search for how other Python TUI tools (Rich, Textual, prompt_toolkit)
  implement live-updating status panels; (2) "code_reader" - read bob/tui/interface.py and identify exactly where and how the spinner and tool-call display currently works; (3) "design_agent" -
  based only on the plan description in your context, draft a concrete implementation plan for the agents panel upgrade. Wait for all three then summarize what to do next.

  This hammers all three slots simultaneously. Watch the TUI show three ⟳ [name] spawned lines and the spinner label cycling through active agent names.

  ---