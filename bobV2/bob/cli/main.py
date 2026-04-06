from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional
import typer

app = typer.Typer(
    name="bob",
    help="bob — Your AI-Powered Development Partner",
    no_args_is_help=False,
    invoke_without_command=True,
)


def _get_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        typer.echo("Error: OPENAI_API_KEY environment variable not set.", err=True)
        raise typer.Exit(1)
    return key


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

        await run_interface(session=session, config=config)
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


@mcp_app.command("add")
def mcp_add(
    name: str = typer.Argument(..., help="Server name"),
    command: list[str] = typer.Argument(..., help="Command and args"),
) -> None:
    """Add an MCP server to config."""
    # Loading config to know the config file location
    from bob.config.loader import load_config

    config = load_config()
    typer.echo(f"Adding MCP server '{name}': {' '.join(command)}")
    typer.echo("(Config file update not yet implemented — edit ~/.bob/config.toml manually.)")


@mcp_app.command("list")
def mcp_list() -> None:
    """List configured MCP servers."""
    from bob.config.loader import load_config

    config = load_config()
    if not config.mcp_servers:
        typer.echo("No MCP servers configured.")
        return
    for srv_name, srv in config.mcp_servers.items():
        typer.echo(f"  {srv_name}: {' '.join(srv.command)}")


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


def cli_main() -> None:
    app()


if __name__ == "__main__":
    cli_main()
