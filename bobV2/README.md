# Bob V2

Bob V2 is a terminal-based AI coding assistant prototype. It runs in your shell, can read and edit files, execute commands with approval controls, use multiple LLM providers, and launch subagents for background research or coding work.

This README is split into two parts:

1. How to install, configure, and use Bob.
2. What Bob is, how it works internally, and what this prototype is not.

MacBook-specific setup notes live in [MACBOOK_SETUP.md](MACBOOK_SETUP.md).

---

## Part 1: Setup And Usage

### Requirements

- Python 3.11 or newer
- Git
- An API key for at least one supported LLM provider
- A terminal that supports ANSI output

On Windows, use PowerShell and the Python launcher (`py -3.11`). On macOS/Linux, use `python3.11`.

### Install From This Repository

#### Windows

```powershell
cd C:\path\to\BobV2\bobV2
py -3.11 -m pip install -e .
```

#### macOS

```bash
brew install python@3.11 pipx git
pipx ensurepath
pipx install -e /absolute/path/to/BobV2/bobV2
```

For a fuller Mac workflow, see [MACBOOK_SETUP.md](MACBOOK_SETUP.md).

#### Linux

```bash
cd /path/to/BobV2/bobV2
python3.11 -m pip install -e .
```

Editable install mode (`-e`) is recommended for development because code changes take effect without reinstalling.

### Configure API Keys

Bob loads environment variables from your shell and from `.env` files. The easiest setup is to copy `.env.example`:

```bash
cp .env.example .env
```

Then edit `.env` and add at least one provider key.

Common keys:

```bash
OPENAI_API_KEY="sk-..."
ANTHROPIC_API_KEY="sk-ant-..."
GEMINI_API_KEY="..."
KIMI_API_KEY="sk-kimi-..."
OPENROUTER_API_KEY="sk-or-..."
```

PowerShell example:

```powershell
$env:KIMI_API_KEY = "sk-kimi-..."
py -3.11 -m bob
```

macOS/Linux example:

```bash
export KIMI_API_KEY="sk-kimi-..."
python3.11 -m bob
```

Bob also supports `BOB_HOME`. If set, Bob stores config, sessions, logs, plugins, and `.env` under that directory. If unset, Bob defaults to `~/.bob`.

### Run Bob

After installation:

```bash
bob
```

Alternative commands:

```bash
bob_v2
python3.11 -m bob
```

Windows launcher:

```powershell
py -3.11 -m bob
```

### First Things To Try

At the prompt, type a request and press Enter:

```text
explain this repository
write tests for the auth module
run the tests and fix the first failure
refactor this file to make it easier to understand
find every place where sessions are created
```

Bob works best when you are specific about the files, goal, and expected outcome.

### Mention Files

Use `@` to include a file as context:

```text
@README.md rewrite the install section
@bob/core/session.py explain how sessions work
```

### Run Shell Commands Directly

Prefix a command with `!` to run it directly:

```text
!git status
!python -m pytest -q
!npm install
```

Shell commands may require approval depending on your configuration.

### Paste Images

Copy an image to your clipboard, then press `Ctrl+V` or paste in the terminal. Bob will attach the image when the terminal and environment support clipboard image paste.

### Useful Slash Commands

Type `/` to open slash-command completion.

| Command | Use |
| --- | --- |
| `/help` | Show commands |
| `/model` | Switch model |
| `/status` | Show current session/model/token state |
| `/new` | Start a new session |
| `/resume` | Resume a saved session |
| `/compact` | Compress context when the chat gets long |
| `/diff` | Show current Git changes |
| `/review` | Ask Bob to review current changes |
| `/commit` | Generate a commit from staged changes |
| `/branch <name>` | Create and switch to a branch |
| `/plan` | Move into a planning/read-only style workflow |
| `/agents` | Manage/message running subagents |
| `/tasks [status]` | List background tasks |
| `/mcp` | Show configured MCP servers |
| `/plugins` | Browse plugins |
| `/cost` | Show estimated cost |
| `/usage` | Show recent token usage |
| `/quit` or `/exit` | Exit Bob |

### Keyboard Shortcuts

| Key | Action |
| --- | --- |
| `Enter` | Send message |
| `Tab` | Complete slash commands |
| `Ctrl+C` | Interrupt current turn |
| `Ctrl+C` twice | Exit |
| `Up` / `Down` while agents run | Inspect running subagents |
| `Enter` while subagent inspector is open | Show details for selected subagent |
| `Esc` while subagent inspector is open | Close inspector |

### Approval Prompts

When Bob wants to run a command or modify something sensitive, it may ask for approval:

```text
Approval required
Command: npm install
CWD:     /path/to/project

y approve   a approve for session   n deny   s abort
```

Only approve commands you understand. Bob is a prototype and may make mistakes.

### Configuration

Create a config file at `~/.bob/config.toml`, or at `$BOB_HOME/config.toml` if `BOB_HOME` is set.

Example:

```toml
model = "kimi/kimi-for-coding"
ask_for_approval = "unless-trusted" # never | unless-trusted | on-request
theme = "dark"
```

You can also use the config CLI:

```bash
bob config get model
bob config set model kimi/kimi-for-coding
bob config list
bob config unset model
```

### Non-Interactive Mode

Run a one-shot command without the interactive TUI:

```bash
bob exec "summarize this repository"
bob exec --json "list the main modules" > output.jsonl
bob exec --full-auto "run and fix tests"
```

### App Server / IDE Mode

Bob can also run as an app server for editor integrations:

```bash
bob app-server --stdio
bob app-server --port 8765
```

### MCP Servers

Bob can connect to MCP servers:

```bash
bob mcp add my-server npx -y @my/mcp-server
bob mcp list
```

### Plugins

```bash
bob plugin list
bob plugin install <name>
bob plugin uninstall <name>
bob plugin search <query>
```

---

## Part 2: What Bob V2 Is

### Short Version

Bob V2 is an experimental AI coding-agent prototype. It is meant to explore what a terminal-first coding assistant can do: understand a repository, answer questions, edit files, run commands, review changes, and coordinate background subagents.

It is not a polished product. It is not an official IBM product. It is not a representation of IBM engineering standards, IBM security practices, IBM legal positions, IBM design practices, IBM fellows, IBM employees, IBM management, or IBM as a company.

### Project Status

Bob V2 was made by IBM high school co-ops as an MVP/prototype-style project. It should be treated as experimental student/co-op work, not as production software.

The goal was to learn, explore, and build a working proof of concept around AI coding agents. Some pieces are ambitious, some are rough, and some are expected to change or break.

### Important Disclaimer

This project may mention IBM because it was built by IBM high school co-ops. However:

- Bob V2 is not an official IBM product.
- Bob V2 does not represent IBM.
- Bob V2 does not represent IBM's engineering, security, legal, privacy, accessibility, AI, or operational practices.
- Bob V2 does not represent IBM fellows, IBM employees, IBM leadership, IBM clients, or IBM partners.
- Nothing in this repository should be treated as IBM guidance, IBM endorsement, IBM policy, IBM documentation, or IBM support material.
- Use it at your own risk.
- The authors and contributors are not responsible for damage, data loss, leaked secrets, broken repositories, incorrect code, unexpected command execution, API charges, or any other outcome from using it.

This is a prototype. Review everything it does.

### What Bob Can Do

Bob is designed to help with common software-engineering tasks:

- Read and summarize code.
- Search through a repository.
- Edit files.
- Run tests and shell commands.
- Explain architecture.
- Review diffs.
- Create commits.
- Work with multiple model providers.
- Use tools such as file read/write, grep, shell, web search/fetch, MCP tools, and browser-related integrations.
- Spawn subagents for background exploration or parallel work.

### How The Interactive TUI Works

The interactive terminal UI is built around a normal chat loop:

1. Bob starts a session and prints the welcome header.
2. You type a request.
3. Bob sends the request plus context to the selected model.
4. The model can request tool calls.
5. Bob executes approved tools and streams results back into the session.
6. Bob prints the assistant's response.
7. The session is saved so it can be resumed later.

The TUI is not a full-screen application. It mostly writes styled terminal output into scrollback, with small live-updating areas for spinners and subagent status.

### How Tool Use Works

Tools are the bridge between the model and your computer. Depending on the request and approval settings, Bob may use tools to:

- Read files.
- Search files.
- Write or patch files.
- Run shell commands.
- Query web pages.
- Manage background tasks.
- Spawn or inspect subagents.

The model proposes tool calls. Bob validates and runs them. Some actions require approval. You should still inspect changes before trusting them.

### How Subagents Work

Subagents are background agents that can work on a focused task while the main session continues. They are useful when a request benefits from parallel exploration, such as:

- "Understand this project and compare it to another project."
- "Search the codebase while also researching external docs."
- "Investigate multiple possible causes of a bug."

When subagents are running, Bob shows a compact status line. Use the arrow keys to inspect them:

- `Up` / `Down`: open or move through the subagent inspector.
- `Enter`: show detail for the selected subagent.
- `Esc`: close the inspector.

Subagents are powerful but experimental. They may use many tokens, take time, or return incomplete results.

### How Sessions And Logs Work

Bob stores session data under `~/.bob` by default, or under `BOB_HOME` if configured. Typical runtime data includes:

- `sessions/`: saved conversation/event history.
- `logs/actions/`: tool and action logs.
- `logs/tui/`: terminal UI logs.
- `config.toml`: user configuration.
- `.env`: optional local environment variables.

Runtime state is intentionally ignored by Git. Do not commit `.bob` or secret-containing files.

### Supported Providers

Bob uses LiteLLM-style provider routing and supports many providers, depending on installed dependencies and configured keys.

Common examples:

| Provider | Example model prefix | Environment variable |
| --- | --- | --- |
| OpenAI | `gpt-4o`, `o3`, `gpt-5.1-codex-mini` | `OPENAI_API_KEY` |
| Anthropic | `anthropic/claude-3.5-sonnet` | `ANTHROPIC_API_KEY` |
| Google Gemini | `gemini/gemini-2.5-pro` | `GEMINI_API_KEY` |
| Google Vertex AI | `vertex_ai/gemini-2.5-pro` | Google credentials / location |
| Azure OpenAI | `azure/<deployment>` | `AZURE_API_KEY` |
| Kimi | `kimi/kimi-for-coding` | `KIMI_API_KEY` |
| OpenRouter | `openrouter/...` | `OPENROUTER_API_KEY` |
| Groq | `groq/...` | `GROQ_API_KEY` |
| Mistral | `mistral/...` | `MISTRAL_API_KEY` |
| xAI | `xai/...` | `XAI_API_KEY` |
| Together AI | `together_ai/...` | `TOGETHERAI_API_KEY` |
| Ollama | `ollama/llama3.1` | none for local default |

### Safety Notes

Bob can edit files and run commands. Treat it like an experimental automation tool with shell access.

Recommended safety practices:

- Use Git and commit before large changes.
- Review every diff.
- Keep secrets out of prompts when possible.
- Use `.env` files carefully.
- Do not approve commands you do not understand.
- Run tests after changes.
- Start in a throwaway branch or test repository if unsure.

### Development Notes

Install in editable mode and run tests:

```bash
python3.11 -m pip install -e ".[dev]"
python3.11 -m pytest
```

On Windows:

```powershell
py -3.11 -m pip install -e ".[dev]"
py -3.11 -m pytest
```

The main package lives in `bob/`. The CLI entry point is `bob.cli.main:cli_main`, exposed as both `bob` and `bob_v2`.

### Final Reminder

Bob V2 is a prototype made for exploration and learning. It can be useful, but it is not production-grade and not official IBM software. You are responsible for reviewing, testing, and deciding whether any output or code change is safe to use.
