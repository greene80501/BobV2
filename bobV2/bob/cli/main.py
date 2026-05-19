from __future__ import annotations

# Windows: LiteLLM opens tokenizer JSON files via importlib.resources without
# specifying encoding='utf-8', causing UnicodeDecodeError on cp1252 systems.
# Fix: if not already in UTF-8 mode, re-exec immediately with -X utf8.
# This must run before any import that could trigger litellm's tokenizer load.
import sys as _sys
if _sys.platform == "win32" and not _sys.flags.utf8_mode:
    import os as _os
    import subprocess as _subprocess
    _sys.exit(_subprocess.run(
        [_sys.executable, "-X", "utf8", "-m", "bob"] + _sys.argv[1:],
        env=_os.environ,
    ).returncode)

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional
import typer

from bob.paths import bob_home

app = typer.Typer(
    name="bob",
    help="bob — Your AI-Powered Development Partner",
    no_args_is_help=False,
    invoke_without_command=True,
)
@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    prompt: Optional[str] = typer.Option(None, "-p", "--prompt", help="Initial message to send"),
    model: Optional[str] = typer.Option(None, "-m", "--model", help="Model to use"),
    sandbox: Optional[str] = typer.Option(None, "-s", "--sandbox", help="Sandbox mode"),
    approval: Optional[str] = typer.Option(None, "-a", "--approval", help="Approval policy"),
    resume: Optional[str] = typer.Option(None, "--resume", help="Resume session by ID"),
    cwd: Optional[Path] = typer.Option(None, "-C", "--cd", help="Working directory"),
) -> None:
    """Launch bob interactive TUI."""
    if ctx.invoked_subcommand is not None:
        return

    from bob.config.loader import load_config

    work_dir = cwd or Path.cwd()

    cli_overrides: dict = {}
    if model:
        cli_overrides["model"] = model
    if sandbox:
        cli_overrides["sandbox_mode"] = sandbox
    if approval:
        cli_overrides["ask_for_approval"] = approval

    config = load_config(cwd=work_dir, cli_overrides=cli_overrides)

    async def run() -> None:
        from bob.core.session import BobSession
        from bob.tui.interface import run_interface

        try:
            session = BobSession(config=config, cwd=work_dir)
        except RuntimeError as e:
            typer.echo(f"\n  ✗ {e}", err=True)
            raise typer.Exit(1)

        await session.start()

        if resume:
            await session.resume_by_id(resume)

        if prompt:
            # Queue the initial prompt — it will be sent once the event loop starts
            async def _send_initial() -> None:
                await asyncio.sleep(0.1)
                from bob.protocol.ops import UserTurnOp
                from bob.protocol.items import TextUserInput
                await session.submit(
                    UserTurnOp(items=[TextUserInput(type="text", text=prompt)])
                )
            asyncio.create_task(_send_initial())

        final_model = await run_interface(session=session, config=config)
        # Persist the last active model so the next conversation starts with it.
        from bob.config.editor import set_value
        try:
            set_value("model", final_model)
        except Exception:
            pass
        await session.shutdown()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    import os as _os
    _os._exit(0)


@app.command()
def exec(
    prompt: Optional[str] = typer.Argument(None, help="Prompt to send (reads stdin if not provided)"),
    model: Optional[str] = typer.Option(None, "-m", "--model"),
    sandbox: Optional[str] = typer.Option(None, "-s", "--sandbox"),
    approval: Optional[str] = typer.Option(None, "-a", "--approval"),
    resume: Optional[str] = typer.Option(None, "--resume"),
    last: bool = typer.Option(False, "--last", help="Resume most recent session"),
    json_output: bool = typer.Option(False, "--json", help="Output events as JSONL"),
    ephemeral: bool = typer.Option(False, "--ephemeral", help="Don't persist session"),
    full_auto: bool = typer.Option(False, "--full-auto", help="Auto-approve everything"),
    yolo: bool = typer.Option(False, "--yolo", help="Danger: bypass all approvals and sandbox"),
    cwd: Optional[Path] = typer.Option(None, "-C", "--cd"),
    output_file: Optional[Path] = typer.Option(None, "-o", "--output-last-message"),
) -> None:
    """Run bob non-interactively."""
    from bob.cli.exec_cmd import run_exec

    asyncio.run(
        run_exec(
            prompt=prompt,
            model=model,
            sandbox=sandbox,
            approval=approval,
            resume_id=resume,
            resume_last=last,
            json_output=json_output,
            ephemeral=ephemeral,
            full_auto=full_auto,
            yolo=yolo,
            cwd=cwd,
            output_file=output_file,
        )
    )


@app.command("app-server")
def app_server(
    stdio: bool = typer.Option(False, "--stdio", help="Use stdin/stdout transport"),
    port: int = typer.Option(8765, "--port", help="WebSocket port"),
) -> None:
    """Start bob as a JSON-RPC 2.0 app server for IDE integrations."""
    from bob.app_server.server import run_server

    asyncio.run(run_server(stdio=stdio, port=port))


mcp_app = typer.Typer(name="mcp", help="Manage MCP servers")
app.add_typer(mcp_app, name="mcp")

config_app = typer.Typer(name="config", help="Read and write bob config values")
app.add_typer(config_app, name="config")


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key in dot-notation (e.g. model or providers.openai.api_key)"),
    value: str = typer.Argument(..., help="Value to set (strings, integers, and true/false booleans are supported)"),
) -> None:
    """Set a config value."""
    from bob.config.editor import set_value
    try:
        set_value(key, value)
        typer.echo(f"  {key} = {value}")
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Config key in dot-notation"),
) -> None:
    """Get a config value."""
    from bob.config.editor import get_value
    result = get_value(key)
    if result:
        typer.echo(result)
    else:
        typer.echo(f"(not set)", err=True)
        raise typer.Exit(1)


@config_app.command("unset")
def config_unset(
    key: str = typer.Argument(..., help="Config key in dot-notation"),
) -> None:
    """Remove a config key."""
    from bob.config.editor import unset_value
    if unset_value(key):
        typer.echo(f"  removed {key}")
    else:
        typer.echo(f"  (key not found: {key})", err=True)


@config_app.command("list")
def config_list_cmd() -> None:
    """List all config values."""
    from bob.config.editor import list_values
    rows = list_values()
    if not rows:
        typer.echo("  (config file is empty or not found)")
        return
    for key, val in rows:
        typer.echo(f"  {key} = {val}")


@mcp_app.command("add")
def mcp_add(
    name: str = typer.Argument(..., help="Server name"),
    command: list[str] = typer.Argument(..., help="Command and args"),
) -> None:
    """Add an MCP server to config."""
    from bob.config.editor import _load_raw, _save_raw
    try:
        data = _load_raw()
        servers = data.setdefault("mcp_servers", {})
        servers[name] = {"command": list(command)}
        _save_raw(data)
        typer.echo(f"  Added MCP server '{name}': {' '.join(command)}")
    except ImportError:
        typer.echo("  Error: tomli_w is required. Run: pip install tomli_w", err=True)
        raise typer.Exit(1)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)


@mcp_app.command("list")
def mcp_list() -> None:
    """List configured MCP servers."""
    from bob.config.loader import load_config
    from bob.plugins.manager import PluginsManager

    config = load_config()
    rows: list[str] = []
    for srv_name, srv in config.mcp_servers.items():
        if getattr(srv, "type", "stdio") == "stdio":
            rows.append(f"  [config] {srv_name}: {' '.join(srv.command)}")
        else:
            rows.append(f"  [config] {srv_name}: {srv.type} {srv.url}")

    plugin_cfgs, _ = PluginsManager.load_plugin_bundles_from_roots(
        [root for _, root in _get_plugin_roots()]
    )
    seen_plugin_servers: set[str] = set()
    for cfg in plugin_cfgs:
        if cfg.server_name in seen_plugin_servers or cfg.server_name in config.mcp_servers:
            continue
        seen_plugin_servers.add(cfg.server_name)
        if cfg.transport == "stdio":
            command = " ".join(cfg.command + cfg.args)
            rows.append(f"  [plugin] {cfg.server_name}: {command}")
        else:
            rows.append(f"  [plugin] {cfg.server_name}: {cfg.transport} {cfg.url}")

    if not rows:
        typer.echo("No MCP servers configured.")
        return
    for row in rows:
        typer.echo(row)


@app.command()
def completion(
    shell: str = typer.Argument(..., help="Shell: bash or zsh"),
) -> None:
    """Print shell completion script."""
    if shell == "bash":
        typer.echo('eval "$(bob --completion bash)"')
    elif shell == "zsh":
        typer.echo('eval "$(bob --completion zsh)"')
    else:
        typer.echo(f"Unknown shell: {shell}", err=True)


@app.command("export-schemas")
def export_schemas() -> None:
    """Export bob protocol v1 JSON schemas."""
    from bob.protocol.v1.export_schemas import export_jsonschemas

    out = export_jsonschemas(Path(__file__).resolve().parents[1] / "protocol" / "v1" / "schemas")
    typer.echo(f"Exported {len(out)} schema files")


plugin_app = typer.Typer(name="plugin", help="Manage bob plugins")
app.add_typer(plugin_app, name="plugin")


def _get_plugins_manager():
    from bob.plugins.manager import PluginsManager
    return PluginsManager(bob_home() / "plugins")


def _get_plugin_roots(cwd: Optional[Path] = None) -> list[tuple[str, Path]]:
    active_cwd = (cwd or Path.cwd()).resolve()
    roots = [("user", bob_home() / "plugins")]
    repo_root = active_cwd / ".bob" / "plugins"
    if repo_root not in [root for _, root in roots]:
        roots.append(("repo", repo_root))
    return roots


def _collect_plugins(cwd: Optional[Path] = None) -> list[tuple[str, object]]:
    from bob.plugins.manager import PluginsManager

    collected: list[tuple[str, object]] = []
    seen: set[str] = set()
    for scope, root in _get_plugin_roots(cwd):
        pm = PluginsManager(root)
        for plugin in pm.list_plugins():
            key = plugin.name.lower()
            if key in seen:
                continue
            seen.add(key)
            collected.append((scope, plugin))
    return collected


@plugin_app.command("list")
def plugin_list() -> None:
    """List installed plugins."""
    plugins = _collect_plugins()
    if not plugins:
        typer.echo("  No plugins installed.")
        return
    for scope, p in plugins:
        status = "" if p.enabled else " [disabled]"
        typer.echo(f"  [{scope}] {p.name}@{p.version}{status} — {p.description}")


@plugin_app.command("install")
def plugin_install(
    source: str = typer.Argument(..., help="Plugin name (from registry), URL, or local path"),
    registry_url: str = typer.Option("", "--registry", help="Custom registry URL"),
) -> None:
    """Install a plugin from the registry, a URL, or a local path."""
    from pathlib import Path as _Path
    pm = _get_plugins_manager()
    info = None

    local = _Path(source)
    if local.exists():
        info = pm.install_from_path(local)
    elif source.startswith("http://") or source.startswith("https://"):
        typer.echo(f"  Downloading {source}…")
        info = pm.install_from_url(source)
    else:
        typer.echo(f"  Looking up '{source}' in registry…")
        info = pm.install_from_registry(source, registry_url)

    if info:
        typer.echo(f"  Installed {info.name}@{info.version}")
    else:
        typer.echo(f"  Failed to install '{source}'", err=True)
        raise typer.Exit(1)


@plugin_app.command("uninstall")
def plugin_uninstall(
    name: str = typer.Argument(..., help="Plugin name to remove"),
) -> None:
    """Uninstall a plugin."""
    pm = _get_plugins_manager()
    if pm.uninstall(name):
        typer.echo(f"  Removed {name}")
    else:
        typer.echo(f"  Plugin '{name}' not found", err=True)
        raise typer.Exit(1)


@plugin_app.command("search")
def plugin_search(
    query: str = typer.Argument(..., help="Search term"),
    registry_url: str = typer.Option("", "--registry", help="Custom registry URL"),
) -> None:
    """Search the plugin registry."""
    pm = _get_plugins_manager()
    typer.echo(f"  Searching for '{query}'…")
    results = pm.search_registry(query, registry_url)
    if not results:
        typer.echo("  No results found.")
        return
    for p in results:
        typer.echo(f"  {p.get('name', '?')}@{p.get('version', '?')} — {p.get('description', '')}")


def cli_main() -> None:
    app()


if __name__ == "__main__":
    cli_main()
