# bob — AI-Powered Development Partner

bob is a terminal AI coding agent. It runs in your shell, reads and edits files, executes commands, and works across every major LLM provider.

---

## Requirements

- Python 3.11+
- An API key for at least one supported provider

---

## Install

### Windows

```powershell
cd C:\path\to\bob_v2_new_code_geb\bobV2
py -3.11 -m pip install -e .
```

### macOS

```bash
cd /path/to/bob_v2_new_code_geb/bobV2
python3.11 -m pip install -e .
```

### Linux

```bash
cd /path/to/bob_v2_new_code_geb/bobV2
python3.11 -m pip install -e .
```

---

## Set Your API Key (.env recommended)

Best practice: create a `.env` file (project root or `~/.bob/.env`). Bob auto-loads both.

```bash
cp .env.example .env
# then edit .env with your keys
```

Pick one provider to start. You can also set keys directly in your shell:

### Windows (PowerShell)

```powershell
$env:OPENAI_API_KEY      = "sk-..."          # OpenAI
$env:ANTHROPIC_API_KEY   = "sk-ant-..."      # Anthropic / Claude
$env:GEMINI_API_KEY      = "..."             # Google Gemini
$env:KIMI_API_KEY        = "sk-kimi-..."     # Kimi for Coding
$env:OPENROUTER_API_KEY  = "sk-or-..."       # OpenRouter (any model)
```

To make a key permanent, add it to your PowerShell profile:
```powershell
notepad $PROFILE
# Add: $env:OPENAI_API_KEY = "sk-..."
```

### macOS / Linux

```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="..."
export KIMI_API_KEY="sk-kimi-..."
export OPENROUTER_API_KEY="sk-or-..."
```

To make a key permanent, add it to `~/.zshrc` or `~/.bash_profile`:
```bash
echo 'export OPENAI_API_KEY="sk-..."' >> ~/.zshrc && source ~/.zshrc
```

---

## Run

### Windows

```powershell
bob
```

If `bob` is not on your PATH:
```powershell
C:\Users\<you>\AppData\Local\Programs\Python\Python311\Scripts\bob.exe
```

### macOS / Linux

```bash
bob
```

If `bob` is not found:
```bash
python3.11 -m bob
```

---

## Basic Usage

Just type your request and press Enter.

```
> explain what this project does

> write tests for the auth module

> run the tests and fix any failures

> refactor the database layer to use async
```

### Shell passthrough

Prefix with `!` to run a shell command directly without sending it to the model:
```
> !git status
> !python -m pytest -x
> !npm install
```

### File mentions

Prefix with `@` to include a file as context:
```
> @src/main.py explain this file
> @README.md update this to reflect recent changes
```

### Paste an image

Copy an image to your clipboard, then press **Ctrl+V** (or right-click paste) in the input. Bob will attach it automatically.

---

## Slash Commands

Type `/` and press Tab to autocomplete. Full list:

| Command | Description |
|---------|-------------|
| `/model` | Switch model (opens picker) |
| `/fast` | Toggle Fast mode |
| `/effort` | Set reasoning effort: low / medium / high |
| `/think [N]` | Set thinking token budget for next turn |
| `/status` | Show model, session, token usage |
| `/resume` | Pick a saved session to resume |
| `/new` | Start a fresh session |
| `/fork` | Fork the current session |
| `/rename` | Rename the current session |
| `/compact` | Summarize context to free token space |
| `/plan` | Enter Plan mode (read-only exploration) |
| `/diff` | Show git diff including untracked files |
| `/review` | Review current changes for issues |
| `/commit` | Generate a commit message and commit staged changes |
| `/branch <name>` | Create and checkout a new git branch |
| `/init` | Generate an AGENTS.md for the project |
| `/context <url\|path>` | Add a URL or file as context |
| `/export` | Export conversation to Markdown |
| `/summary` | Summarize what's been done this session |
| `/rewind [N]` | Undo the last N turns |
| `/copy` | Copy the latest bob output to clipboard |
| `/mention` | Mention a file |
| `/approvals` | Configure what bob is allowed to do |
| `/sandbox-add-read-dir <path>` | Allow sandbox to read a directory |
| `/collab` | Change collaboration mode |
| `/skills` | Manage skills |
| `/hooks` | List configured hooks |
| `/mcp` | List MCP tools |
| `/apps` | Manage apps |
| `/plugins` | Browse plugins |
| `/personality` | Choose communication style |
| `/output-style` | Set response style: brief / normal / verbose |
| `/brief` | Alias for `/output-style brief` |
| `/theme` | Choose syntax highlighting theme |
| `/statusline` | Configure status line items |
| `/title` | Configure terminal title items |
| `/vi` | Toggle vi input mode |
| `/tasks [status]` | List tasks |
| `/cost` | Show estimated token cost |
| `/usage` | Show token usage for last turn |
| `/ps` | List background terminals |
| `/stop` | Stop all background terminals |
| `/doctor` | Run system health checks |
| `/debug-config` | Show config layers |
| `/clear` | Clear terminal and context |
| `/help` | Show all commands |
| `/quit` / `/exit` | Exit bob |

---

## Approval Prompts

When bob wants to run a shell command:

```
  Approval required
  Command: $ npm install
  CWD:     /my-project

  y approve   a approve-all   n reject   d abort turn
```

| Key | Action |
|-----|--------|
| `y` | Approve this one command |
| `a` | Approve all commands for this session |
| `n` | Reject this command |
| `d` | Abort the entire turn |

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `Tab` | Autocomplete slash command |
| `Up / Down` | Browse input history |
| `Ctrl+V` | Paste (text or image from clipboard) |
| `Ctrl+C` | Interrupt running turn |
| `Ctrl+C` twice | Exit |

---

## Config File

Create `~/.bob/config.toml` to set persistent defaults.

Tip: keep secrets in `.env` instead of putting API keys directly in `config.toml`.

```toml
model = "gpt-5.1-codex-mini"
ask_for_approval = "unless-trusted"   # never | unless-trusted | on-request

[providers.openai]
api_key = "sk-..."

[providers.anthropic]
api_key = "sk-ant-..."

[providers.gemini]
api_key = "..."

[providers.kimi]
api_key = "sk-kimi-..."

[providers.openrouter]
api_key = "sk-or-..."
```

Or use the CLI to set values without editing the file:

```bash
bob config set model gpt-4o
bob config get model
bob config list
bob config unset model
```

---

## Supported Providers

| Provider | Model prefix | Key env var |
|----------|-------------|-------------|
| OpenAI | `gpt-5.1-codex-mini`, `gpt-4o`, `o3`, ... | `OPENAI_API_KEY` |
| Anthropic | `anthropic/claude-3.5-sonnet`, ... | `ANTHROPIC_API_KEY` |
| Google Gemini | `gemini/gemini-2.5-pro`, ... | `GEMINI_API_KEY` |
| Google Vertex AI | `vertex_ai/gemini-2.5-pro` | `VERTEXAI_LOCATION` + credentials |
| Azure OpenAI | `azure/<deployment>` | `AZURE_API_KEY` |
| Kimi for Coding | `kimi/kimi-for-coding` | `KIMI_API_KEY` |
| OpenRouter | `openrouter/openai/gpt-4o`, ... | `OPENROUTER_API_KEY` |
| Groq | `groq/llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| Mistral | `mistral/mistral-large-latest` | `MISTRAL_API_KEY` |
| xAI (Grok) | `xai/grok-2-latest` | `XAI_API_KEY` |
| Together AI | `together_ai/...` | `TOGETHERAI_API_KEY` |
| Ollama (local) | `ollama/llama3.1` | none |

---

## Non-Interactive Mode

Run bob without the TUI:

```bash
bob exec "what files are in this directory?"
bob exec --last "continue the previous task"
bob exec --json "list all functions" > output.jsonl
bob exec --full-auto "run and fix all tests"
bob exec --ephemeral "one-shot query, no session saved"
```

---

## IDE / App Server

Start bob as a JSON-RPC server for IDE extensions:

```bash
bob app-server --stdio      # stdin/stdout transport
bob app-server --port 8765  # WebSocket transport
```

---

## MCP Servers

Add an MCP server:
```bash
bob mcp add my-server npx -y @my/mcp-server
```

List configured servers:
```bash
bob mcp list
```

---

## Plugins

```bash
bob plugin list
bob plugin install <name>
bob plugin uninstall <name>
bob plugin search <query>
```
