"""GrayBench CLI – multi-benchmark testing suite."""

import sys
import logging
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from graybench import __version__

console = Console()

# Initialize DB on import
def _ensure_db():
    from graybench.db.engine import init_db
    init_db()


@click.group()
@click.version_option(version=__version__, prog_name="graybench")
def main():
    """GrayBench – Multi-benchmark testing suite for LLMs."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )
    _ensure_db()


# ─── run ─────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("benchmark", type=click.Choice(["qiskitbench", "qiskitbench-hard", "critpt"]))
@click.option("--model", "-m", required=True, help="Model string: provider/model_id (e.g., google/gemini-3-flash-preview)")
@click.option("--route", "-r", type=click.Choice(["direct", "openrouter"]), default="direct", help="Provider route")
@click.option("--tasks", "-t", type=int, default=None, help="Limit number of tasks")
@click.option("--parallel", "-p", type=int, default=1, help="Parallel task execution")
@click.option("--task-id", "task_ids", default=None, help="Run specific task(s) by ID (comma-separated, e.g. qiskitHumanEval/43)")
def run(benchmark, model, route, tasks, parallel, task_ids):
    """Run a benchmark suite."""
    from graybench.llm.registry import get_provider
    from graybench.benchmarks.base import get_benchmark
    from graybench.benchmarks.runner import BenchmarkRunner

    console.print(f"\n[bold cyan]GrayBench[/bold cyan] – Running [bold]{benchmark}[/bold]")
    console.print(f"  Model:    [yellow]{model}[/yellow]")
    console.print(f"  Route:    {route}")
    if tasks:
        console.print(f"  Tasks:    {tasks}")
    console.print()

    # Parse model string
    if "/" in model:
        provider_name, model_id = model.split("/", 1)
    else:
        provider_name, model_id = "", model

    try:
        llm = get_provider(model, route=route)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    bench = get_benchmark(benchmark)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task(f"Running {benchmark}", total=None)

        def on_progress(event):
            if event["type"] == "task_started":
                total = event.get("total", 0)
                progress.update(task_id, total=total,
                               description=f"[{event['index']+1}/{total}] {event['task_id']}")
            elif event["type"] == "task_completed":
                progress.advance(task_id)

        runner = BenchmarkRunner(
            benchmark=bench,
            llm=llm,
            parallel=parallel,
            on_progress=on_progress,
        )
        # Parse --task-id into a list
        tid_list = None
        if task_ids:
            tid_list = [t.strip() for t in task_ids.split(",") if t.strip()]

        run_id = runner.run(
            task_limit=tasks,
            route=route,
            model_provider=provider_name,
            model_id=model_id,
            task_ids=tid_list,
        )

    # Show results
    _show_run_results(run_id)


def _show_run_results(run_id: str):
    """Display run results in a rich table."""
    from graybench.benchmarks.scorer import get_run_summary
    summary = get_run_summary(run_id)
    if not summary:
        console.print(f"[red]Run {run_id} not found[/red]")
        return

    status_color = "green" if summary["status"] == "completed" else "red"
    score_pct = (summary["score"] or 0) * 100

    console.print()
    console.print(Panel(
        f"[bold]Run ID:[/bold] {summary['run_id']}\n"
        f"[bold]Benchmark:[/bold] {summary['benchmark']}\n"
        f"[bold]Model:[/bold] {summary['model']}\n"
        f"[bold]Route:[/bold] {summary['route']}\n"
        f"[bold]Status:[/bold] [{status_color}]{summary['status']}[/{status_color}]\n"
        f"\n"
        f"[bold]Score:[/bold] [cyan]{score_pct:.1f}%[/cyan]\n"
        f"[bold]Passed:[/bold] [green]{summary['passed']}[/green] / {summary['total']}\n"
        f"[bold]Failed:[/bold] [red]{summary['failed']}[/red] / {summary['total']}\n"
        f"[bold]Cost:[/bold] ${summary['cost_usd']:.4f}\n"
        f"[bold]Duration:[/bold] {summary['duration_s']:.1f}s",
        title="[bold cyan]Results[/bold cyan]",
        border_style="cyan",
    ))

    # Task-level table
    if summary.get("tasks"):
        table = Table(title="Task Results", show_lines=True)
        table.add_column("Task", style="dim")
        table.add_column("Status", justify="center")
        table.add_column("Score", justify="right")
        table.add_column("Failure", justify="left")
        table.add_column("Duration", justify="right")

        for t in summary["tasks"]:
            status = "[green]PASS[/green]" if t.get("passed") else "[red]FAIL[/red]"
            score = f"{(t.get('score') or 0)*100:.0f}%"
            failure = t.get("failure_category", "") or ""
            dur = f"{t.get('duration_s', 0):.1f}s"
            table.add_row(t.get("task_id", "?"), status, score, failure, dur)

        console.print(table)


# ─── models ──────────────────────────────────────────────────────────────────

@main.group()
def models():
    """Manage the models registry."""
    pass


@models.command("list")
@click.option("--provider", "-p", help="Filter by provider")
def models_list(provider):
    """List all models with pricing."""
    from graybench.db import models_db
    items = models_db.list_models(provider=provider)

    if not items:
        console.print("[yellow]No models found.[/yellow]")
        return

    table = Table(title="Models Registry", show_lines=True)
    table.add_column("Provider", style="cyan")
    table.add_column("Model ID", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Input $/M", justify="right")
    table.add_column("Cached $/M", justify="right")
    table.add_column("Output $/M", justify="right")

    for m in items:
        status = "[green]active[/green]" if m["status"] == "active" else f"[yellow]{m['status']}[/yellow]"
        inp = f"${m['input_price_per_m']:.2f}" if m.get("input_price_per_m") is not None else "—"
        cached = f"${m['cached_price_per_m']:.3f}" if m.get("cached_price_per_m") is not None else "N/A"
        out = f"${m['output_price_per_m']:.2f}" if m.get("output_price_per_m") is not None else "—"
        table.add_row(m["provider"], m["model_id"], status, inp, cached, out)

    console.print(table)
    console.print(f"\n[dim]{len(items)} models[/dim]")


@models.command("add")
@click.option("--provider", "-p", required=True)
@click.option("--model-id", "-m", required=True)
@click.option("--display-name", "-n", required=True)
@click.option("--input-price", type=float, help="Input $/M tokens")
@click.option("--cached-price", type=float, help="Cached $/M tokens")
@click.option("--output-price", type=float, help="Output $/M tokens")
@click.option("--openrouter-id", help="OpenRouter model path")
def models_add(provider, model_id, display_name, input_price, cached_price, output_price, openrouter_id):
    """Add a custom model."""
    from graybench.db import models_db
    models_db.add_model(
        provider=provider, model_id=model_id, display_name=display_name,
        input_price_per_m=input_price, cached_price_per_m=cached_price,
        output_price_per_m=output_price, openrouter_id=openrouter_id,
    )
    console.print(f"[green]Added[/green] {provider}/{model_id}")


@models.command("remove")
@click.argument("model_string")
def models_remove(model_string):
    """Remove a model (provider/model_id)."""
    from graybench.db import models_db
    if "/" not in model_string:
        console.print("[red]Use provider/model_id format[/red]")
        return
    provider, model_id = model_string.split("/", 1)
    if models_db.remove_model(provider, model_id):
        console.print(f"[green]Removed[/green] {model_string}")
    else:
        console.print(f"[yellow]Not found:[/yellow] {model_string}")


# ─── keys ────────────────────────────────────────────────────────────────────

@main.group()
def keys():
    """Manage API keys."""
    pass


@keys.command("set")
@click.argument("provider")
@click.option("--name", default="default", help="Key name/label")
def keys_set(provider, name):
    """Set an API key for a provider (securely prompted)."""
    from graybench.db import api_keys
    key = click.prompt(f"Enter API key for {provider}", hide_input=True)
    if not key.strip():
        console.print("[red]Empty key, aborting[/red]")
        return
    api_keys.set_key(provider, key.strip(), key_name=name)
    console.print(f"[green]Saved[/green] API key for {provider}")


@keys.command("list")
def keys_list():
    """List configured API keys (values hidden)."""
    from graybench.db import api_keys
    items = api_keys.list_keys()

    if not items:
        console.print("[yellow]No API keys configured.[/yellow]")
        console.print("Use: graybench keys set <provider>")
        return

    table = Table(title="API Keys")
    table.add_column("Provider", style="cyan")
    table.add_column("Name")
    table.add_column("Source")
    table.add_column("Active", justify="center")

    for k in items:
        active = "[green]yes[/green]" if k.get("is_active") else "[red]no[/red]"
        table.add_row(k["provider"], k.get("key_name", ""), k["source"], active)

    console.print(table)


@keys.command("remove")
@click.argument("provider")
@click.option("--name", default="default")
def keys_remove(provider, name):
    """Remove an API key."""
    from graybench.db import api_keys
    if api_keys.delete_key(provider, name):
        console.print(f"[green]Removed[/green] key for {provider}")
    else:
        console.print(f"[yellow]Not found:[/yellow] {provider}/{name}")


@keys.command("test")
@click.argument("provider")
def keys_test(provider):
    """Test if an API key works."""
    from graybench.db import api_keys
    key = api_keys.get_key(provider)
    if not key:
        console.print(f"[red]No key found for {provider}[/red]")
        return

    console.print(f"Testing {provider} key...")
    try:
        if provider == "ibm_quantum":
            # IBM Quantum is a service key, not an LLM provider.
            # Validate by exchanging the API key for an IAM token via IBM Cloud.
            import urllib.request, urllib.parse, json as _json
            data = urllib.parse.urlencode({
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": key,
            }).encode()
            req = urllib.request.Request("https://iam.cloud.ibm.com/identity/token", data=data)
            resp = urllib.request.urlopen(req, timeout=15)
            token_data = _json.loads(resp.read())
            if "access_token" in token_data:
                console.print("[green]OK[/green] – IBM Cloud token exchange succeeded")
            else:
                raise RuntimeError("Token exchange returned no access_token")
        else:
            # Quick test: resolve a provider with a simple model
            from graybench.db import models_db
            model = models_db.list_models(provider=provider)
            if not model:
                console.print(f"[yellow]No models configured for {provider}[/yellow]")
                return
            model_string = f"{provider}/{model[0]['model_id']}"
            from graybench.llm.registry import get_provider
            llm = get_provider(model_string, api_key=key)
            resp = llm.generate("Say hello.", "Hello!", max_tokens=10)
            console.print(f"[green]OK[/green] – Response: {resp[:50]}...")
    except Exception as e:
        console.print(f"[red]Failed:[/red] {e}")


# ─── results ─────────────────────────────────────────────────────────────────

@main.group()
def results():
    """View benchmark results."""
    pass


@results.command("list")
@click.option("--benchmark", "-b", help="Filter by benchmark")
@click.option("--limit", "-l", type=int, default=20)
def results_list(benchmark, limit):
    """List recent benchmark runs."""
    from graybench.db import runs_db
    runs = runs_db.list_runs(benchmark=benchmark, limit=limit)

    if not runs:
        console.print("[yellow]No runs found.[/yellow]")
        return

    table = Table(title="Benchmark Runs", show_lines=True)
    table.add_column("Run ID", style="dim")
    table.add_column("Benchmark")
    table.add_column("Model", style="bold")
    table.add_column("Route")
    table.add_column("Status", justify="center")
    table.add_column("Score", justify="right")
    table.add_column("Pass/Total", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Date")

    for r in runs:
        status_map = {
            "completed": "[green]done[/green]",
            "running": "[yellow]running[/yellow]",
            "failed": "[red]failed[/red]",
            "canceled": "[dim]canceled[/dim]",
            "pending": "[dim]pending[/dim]",
        }
        status = status_map.get(r["status"], r["status"])
        score = f"{(r.get('score') or 0)*100:.1f}%" if r.get("score") is not None else "—"
        pass_total = f"{r.get('passed_tasks', 0)}/{r.get('total_tasks', 0)}"
        cost = f"${r.get('total_cost_usd', 0):.4f}"
        model = f"{r['model_provider']}/{r['model_id']}"

        table.add_row(
            r["run_id"], r["benchmark"], model, r["route"],
            status, score, pass_total, cost,
            r.get("created_at", "")[:16],
        )

    console.print(table)


@results.command("show")
@click.argument("run_id")
def results_show(run_id):
    """Show detailed results for a run."""
    _show_run_results(run_id)


@results.command("compare")
@click.argument("run_id_1")
@click.argument("run_id_2")
def results_compare(run_id_1, run_id_2):
    """Compare two benchmark runs side by side."""
    from graybench.benchmarks.scorer import compare_runs
    cmp = compare_runs(run_id_1, run_id_2)

    if "error" in cmp:
        console.print(f"[red]{cmp['error']}[/red]")
        return

    r1 = cmp["run_1"]
    r2 = cmp["run_2"]

    table = Table(title="Run Comparison", show_lines=True)
    table.add_column("", style="bold")
    table.add_column(r1["run_id"], style="cyan")
    table.add_column(r2["run_id"], style="yellow")

    table.add_row("Model", r1["model"], r2["model"])
    table.add_row("Score", f"{(r1.get('score') or 0)*100:.1f}%", f"{(r2.get('score') or 0)*100:.1f}%")
    table.add_row("Passed", str(r1.get("passed", 0)), str(r2.get("passed", 0)))
    table.add_row("Cost", f"${r1.get('cost_usd', 0):.4f}", f"${r2.get('cost_usd', 0):.4f}")
    table.add_row("Duration", f"{r1.get('duration_s', 0):.1f}s", f"{r2.get('duration_s', 0):.1f}s")

    console.print(table)

    # Task-level comparison
    if cmp.get("task_comparison"):
        task_table = Table(title="Task-Level Comparison", show_lines=True)
        task_table.add_column("Task", style="dim")
        task_table.add_column(f"{r1['run_id']}", justify="center")
        task_table.add_column(f"{r2['run_id']}", justify="center")

        for tc in cmp["task_comparison"]:
            s1 = "[green]PASS[/green]" if tc.get("run_1_passed") else "[red]FAIL[/red]" if tc.get("run_1_passed") is not None else "—"
            s2 = "[green]PASS[/green]" if tc.get("run_2_passed") else "[red]FAIL[/red]" if tc.get("run_2_passed") is not None else "—"
            task_table.add_row(tc["task_id"], s1, s2)

        console.print(task_table)


@results.command("delete")
@click.argument("run_ids")
def results_delete(run_ids):
    """Delete one or more benchmark runs by ID (comma-separated)."""
    from graybench.db import runs_db
    ids = [rid.strip() for rid in run_ids.split(",") if rid.strip()]
    if not ids:
        console.print("[red]No run IDs provided.[/red]")
        return
    deleted = 0
    for rid in ids:
        if runs_db.delete_run(rid):
            console.print(f"  [green]Deleted[/green] {rid}")
            deleted += 1
        else:
            console.print(f"  [yellow]Not found:[/yellow] {rid}")
    console.print(f"\n[bold]{deleted}/{len(ids)}[/bold] runs deleted.")


@results.command("export")
@click.argument("run_id")
@click.option("--format", "fmt", type=click.Choice(["json", "csv"]), default="json")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
def results_export(run_id, fmt, output):
    """Export run results to JSON or CSV."""
    from graybench.benchmarks.scorer import get_run_summary
    import json
    summary = get_run_summary(run_id)
    if not summary:
        console.print(f"[red]Run {run_id} not found[/red]")
        return

    if fmt == "json":
        data = json.dumps(summary, indent=2, default=str)
    else:
        import csv
        import io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["task_id", "passed", "score", "duration_s", "tokens_used", "cost_usd",
                         "input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens",
                         "failure_category", "error"])
        for t in summary.get("tasks", []):
            writer.writerow([
                t.get("task_id"), t.get("passed"), t.get("score"),
                t.get("duration_s"), t.get("tokens_used"), t.get("cost_usd"),
                t.get("input_tokens", 0), t.get("output_tokens", 0),
                t.get("cached_tokens", 0), t.get("reasoning_tokens", 0),
                t.get("failure_category", ""), t.get("error", ""),
            ])
        data = buf.getvalue()

    if output:
        with open(output, "w") as f:
            f.write(data)
        console.print(f"[green]Exported to {output}[/green]")
    else:
        console.print(data)


# ─── server ──────────────────────────────────────────────────────────────────

@main.command()
@click.option("--port", type=int, default=8080, help="Web UI port")
def server(port):
    """Start the web UI server."""
    from graybench.web.app import create_web_app
    app = create_web_app()
    console.print(f"\n[bold cyan]GrayBench Web UI[/bold cyan]")
    console.print(f"  http://localhost:{port}")
    console.print()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


# ─── config ──────────────────────────────────────────────────────────────────

@main.group()
def config():
    """Manage configuration."""
    pass


@config.command("show")
def config_show():
    """Print current configuration."""
    from pathlib import Path
    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    if config_path.exists():
        console.print(config_path.read_text())
    else:
        console.print("[yellow]No config.yaml found[/yellow]")


@config.command("path")
def config_path():
    """Print the config file path."""
    from pathlib import Path
    console.print(str(Path(__file__).resolve().parent.parent / "config.yaml"))


# ─── env ──────────────────────────────────────────────────────────────────────

@main.group()
def env():
    """Manage benchmark execution environments."""
    pass


@env.command("list")
def env_list():
    """List all execution environments."""
    from graybench.environments import list_environments, get_environment
    
    env_names = list_environments()
    if not env_names:
        console.print("[yellow]No environments registered.[/yellow]")
        return
    
    table = Table(title="Execution Environments", show_lines=True)
    table.add_column("Name", style="cyan")
    table.add_column("Display Name")
    table.add_column("Status", justify="center")
    table.add_column("Path")
    
    for name in env_names:
        try:
            environment = get_environment(name)
            exists = environment.exists()
            valid = environment.validate() if exists else False
            
            if valid:
                status = "[green]ready[/green]"
            elif exists:
                status = "[yellow]invalid[/yellow]"
            else:
                status = "[dim]not setup[/dim]"
            
            from pathlib import Path
            venv_path = getattr(environment, 'venv_dir', getattr(environment, 'env_dir', Path('.')))
            table.add_row(
                name,
                environment.display_name,
                status,
                str(venv_path),
            )
        except Exception as e:
            table.add_row(name, "", f"[red]error: {e}[/red]", "")
    
    console.print(table)


@env.command("setup")
@click.argument("environment_name", required=False)
@click.option("--python", "-p", default="python3", help="Python executable to use")
@click.option("--force", "-f", is_flag=True, help="Recreate even if exists")
def env_setup(environment_name, python, force):
    """Set up an execution environment.
    
    If ENVIRONMENT_NAME is not specified, sets up all registered environments.
    """
    from graybench.environments import list_environments, get_environment
    
    if environment_name:
        env_names = [environment_name]
    else:
        env_names = list_environments()
        if not env_names:
            console.print("[yellow]No environments registered.[/yellow]")
            return
    
    for name in env_names:
        try:
            environment = get_environment(name)
            
            if environment.exists():
                if force:
                    console.print(f"[yellow]Removing existing environment '{name}'...[/yellow]")
                    if hasattr(environment, 'destroy'):
                        environment.destroy()
                else:
                    if environment.validate():
                        console.print(f"[green]Environment '{name}' is already ready.[/green] Use --force to recreate.")
                        continue
                    else:
                        console.print(f"[yellow]Environment '{name}' exists but is invalid. Reinstalling...[/yellow]")
                        if hasattr(environment, 'destroy'):
                            environment.destroy()
            
            console.print(f"\n[bold cyan]Setting up environment: {name}[/bold cyan]")
            console.print(f"  Display:  {environment.display_name}")
            if hasattr(environment, 'venv_dir'):
                console.print(f"  Location: {environment.venv_dir}")
            console.print(f"  Python:   {python}")
            console.print()
            
            # Set the python executable if supported
            if hasattr(environment, 'python_executable'):
                environment.python_executable = python
            
            environment.ensure_exists()
            
            if environment.validate():
                console.print(f"[green]Success![/green] Environment '{name}' is ready.")
            else:
                console.print(f"[red]Error:[/red] Environment '{name}' failed validation.")
                
        except Exception as e:
            console.print(f"[red]Failed to setup environment '{name}':[/red] {e}")


@env.command("info")
@click.argument("environment_name")
def env_info(environment_name):
    """Show detailed information about an environment."""
    from graybench.environments import get_environment
    import json
    
    try:
        environment = get_environment(environment_name)
        info = environment.get_info()
        
        console.print(f"\n[bold cyan]{environment.display_name}[/bold cyan]")
        console.print(f"  Name:     {info.get('name')}")
        console.print(f"  Path:     {info.get('venv_path', info.get('venv_dir', 'N/A'))}")
        console.print(f"  Exists:   {info.get('exists', False)}")
        console.print(f"  Valid:    {info.get('valid', False)}")
        
        if 'qiskit_version' in info:
            console.print(f"  Qiskit:   {info['qiskit_version']}")
        
        if 'packages' in info:
            qiskit_packages = [p for p in info['packages'] if p.get('name', '').startswith('qiskit')]
            if qiskit_packages:
                console.print(f"\n[bold]Qiskit Packages:[/bold]")
                for pkg in qiskit_packages:
                    console.print(f"  {pkg['name']}: {pkg['version']}")
                    
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


@env.command("validate")
@click.argument("environment_name")
def env_validate(environment_name):
    """Validate an environment is working correctly."""
    from graybench.environments import get_environment
    
    try:
        environment = get_environment(environment_name)
        
        if not environment.exists():
            console.print(f"[red]Environment '{environment_name}' does not exist.[/red]")
            console.print(f"Run: [cyan]graybench env setup {environment_name}[/cyan]")
            return
        
        console.print(f"Validating environment '{environment_name}'...")
        if environment.validate():
            console.print(f"[green]✓ Environment '{environment_name}' is valid.[/green]")
        else:
            console.print(f"[red]✗ Environment '{environment_name}' failed validation.[/red]")
            
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


if __name__ == "__main__":
    main()
