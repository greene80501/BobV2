# Bob V2 MacBook Setup

This setup is for a MacBook where you want a global `bob` command in Terminal and the ability to run Bob inside any project folder.

## Prerequisites

- macOS with Terminal or iTerm
- Homebrew
- Python 3.11 or newer
- `git`
- an API key for at least one provider
- optional: `node` if you want `js_repl`

Install the basics:

```bash
brew install python@3.11 pipx git
pipx ensurepath
```

Close and reopen Terminal after `pipx ensurepath`.

## Install Bob Globally

Pick the absolute path to the `bobV2/` package directory in this repo.

```bash
REPO_ROOT="/Users/<you>/code/BobV2/bobV2"
pipx install -e "$REPO_ROOT"
```

Verify the command is available:

```bash
which bob
bob --help
python3 -m bob --help
```

## Configure API Keys

Bob auto-loads a user-global `.env` file from `~/.bob/.env` by default.

```bash
mkdir -p ~/.bob
nano ~/.bob/.env
```

Add at least one provider key:

```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...
OPENROUTER_API_KEY=sk-or-...
```

You can also keep project-specific overrides in a project `.env`.

## Optional Persistent Defaults

Set config values without editing TOML manually:

```bash
bob config set model gpt-5.1-codex-mini
bob config set ask_for_approval unless-trusted
bob config list
```

The config file lives at `~/.bob/config.toml` unless you override `BOB_HOME`.

## Run Bob In Any Folder

Default workflow:

```bash
cd ~/code/some-project
bob
```

Bob uses the folder you launched it from as its working directory.

Explicit alternate workflow:

```bash
bob -C ~/code/some-project
```

## Verify The Setup

Start Bob in any repo:

```bash
cd ~/code/some-project
bob
```

Inside Bob, run:

```text
/doctor
```

`/doctor` should confirm:

- Python 3.11+
- `pipx` on `PATH`
- `bob` on `PATH`
- `git` on `PATH`
- provider auth configured
- resolved Bob home and config paths

## Update After Pulling New Code

From the repo root:

```bash
cd /Users/<you>/code/BobV2
git pull
pipx reinstall -e /Users/<you>/code/BobV2/bobV2
```

## Optional Custom Bob Home

If you want Bob's config, logs, sessions, plugins, and `.env` somewhere other than `~/.bob`, set `BOB_HOME` in your shell startup file.

```bash
echo 'export BOB_HOME="$HOME/.config/bob"' >> ~/.zshrc
source ~/.zshrc
mkdir -p "$BOB_HOME"
```

After that, Bob will use:

- `$BOB_HOME/config.toml`
- `$BOB_HOME/.env`
- `$BOB_HOME/plugins/`
- `$BOB_HOME/skills/`

## Troubleshooting

### `bob: command not found`

Run:

```bash
pipx ensurepath
```

Then reopen Terminal and check:

```bash
which pipx
which bob
```

### API key errors

Confirm the key is in `~/.bob/.env` or your project `.env`, then restart Bob.

### Sandbox warning on macOS

If `/doctor` warns that the macOS sandbox is unavailable, Bob still runs, but commands are not isolated by `sandbox-exec`. The CLI will continue to rely on approvals and the configured sandbox mode.

### Wrong folder

If Bob opens in the wrong project, launch it from the target folder:

```bash
cd /path/to/project
bob
```

Or use:

```bash
bob -C /path/to/project
```
