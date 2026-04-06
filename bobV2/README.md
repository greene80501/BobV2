# bob - Your AI-Powered Development Partner

bob is a Python-based AI coding assistant that runs directly in your terminal. It uses OpenAI's `gpt-5.1-codex-mini` model via the Responses API.

---

## Requirements

- Python 3.11+
- An OpenAI API key

---

## Install

From the `bobV2` folder:

```
cd C:\Users\green\bob_v2_new_code_geb\bobV2
pip install -e .
```

> On Windows, use Python 3.11 specifically:
> ```
> py -3.11 -m pip install -e .
> ```

---

## Set your API key

**PowerShell** (recommended):
```powershell
$env:OPENAI_API_KEY = "sk-proj-"
```

**cmd.exe**:
```
set OPENAI_API_KEY=sk-proj-...
```

**bash / zsh**:
```bash
export OPENAI_API_KEY=sk-proj-...
```

To set it permanently, add it to your PowerShell profile or System Environment Variables.

---

## Start bob

```
bob
```

If the `bob` command isn't on your PATH (Windows), run it directly:

```
C:\Users\green\AppData\Local\Programs\Python\Python311\Scripts\bob.exe
```

---

## Usage

Just type. No subcommands needed for normal use.

```
> explain what this project does

> write a function to parse JSON with error handling

> run the tests and fix any failures
```

**Shell passthrough** — prefix with `!` to run a command directly:
```
> !git status
> !python -m pytest
```

**Slash commands** — prefix with `/`, Tab to autocomplete:
```
> /status        show model, session, token usage
> /new           start a fresh conversation
> /compact       summarize context when it gets long
> /rename        rename the current session
> /resume        list saved sessions to resume
> /diff          show git diff
> /model         change the model
> /quit          exit
```

---

## Approvals

When bob wants to run a shell command, it will ask:

```
  Approval required
  Command: $ npm install
  CWD:     C:\my-project

  y approve  a approve-all  n reject  d abort turn
  >
```

| Key | Action |
|-----|--------|
| `y` | Approve this command |
| `a` | Approve all commands for this session |
| `n` | Deny this command |
| `d` | Abort the entire turn |

---

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `Tab` | Autocomplete slash command |
| `Up / Down` | Browse input history |
| `Ctrl+C` | Interrupt running turn |
| `Ctrl+C` twice | Exit bob |

---

## Config file (optional)

Create `~/.bob/config.toml` to set defaults:

```toml
api_key = "sk-<your-key-here>"          # avoids needing the env var
model = "gpt-5.1-codex-mini"
ask_for_approval = "unless-trusted"   # never | unless-trusted | on-request
```
