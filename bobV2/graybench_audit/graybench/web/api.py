"""REST API routes for GrayBench web UI."""

import json
import threading
import logging

from flask import Blueprint, request, jsonify, Response

log = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)

# Track active SSE listeners per run
_sse_events: dict[str, list] = {}


# ─── Runs ────────────────────────────────────────────────────────────────────

@api_bp.route("/runs", methods=["GET"])
def list_runs():
    from graybench.db import runs_db
    benchmark = request.args.get("benchmark")
    limit = int(request.args.get("limit", 50))
    runs = runs_db.list_runs(benchmark=benchmark, limit=limit)
    return jsonify(runs)


@api_bp.route("/runs/<run_id>", methods=["GET"])
def get_run(run_id):
    from graybench.benchmarks.scorer import get_run_summary
    summary = get_run_summary(run_id)
    if not summary:
        return jsonify({"error": "Run not found"}), 404
    return jsonify(summary)


@api_bp.route("/runs", methods=["POST"])
def create_run():
    data = request.get_json()
    benchmark_name = data.get("benchmark")
    model_string = data.get("model")
    route = data.get("route", "direct")
    task_limit = data.get("tasks")
    parallel = data.get("parallel", 1)

    if not benchmark_name or not model_string:
        return jsonify({"error": "benchmark and model are required"}), 400

    # Launch in background thread
    def _run_benchmark():
        try:
            from graybench.llm.registry import get_provider
            from graybench.benchmarks.base import get_benchmark
            from graybench.benchmarks.runner import BenchmarkRunner

            if "/" in model_string:
                provider_name, model_id = model_string.split("/", 1)
            else:
                provider_name, model_id = "", model_string

            llm = get_provider(model_string, route=route)
            bench = get_benchmark(benchmark_name)

            def on_progress(event):
                # Broadcast SSE events
                event_list = _sse_events.get(event.get("run_id", ""), [])
                for q in event_list:
                    q.append(event)

            runner = BenchmarkRunner(
                benchmark=bench, llm=llm,
                parallel=parallel,
                on_progress=on_progress,
            )
            runner.run(
                task_limit=task_limit,
                route=route,
                model_provider=provider_name,
                model_id=model_id,
            )
        except Exception as e:
            log.error("Background run failed: %s", e, exc_info=True)

    # Create a provisional run_id to return immediately
    from graybench.db import runs_db
    if "/" in model_string:
        prov, mid = model_string.split("/", 1)
    else:
        prov, mid = "", model_string

    run_id = runs_db.create_run(
        benchmark=benchmark_name,
        model_provider=prov,
        model_id=mid,
        route=route,
    )

    _sse_events[run_id] = []
    t = threading.Thread(target=_run_benchmark, daemon=True)
    t.start()

    return jsonify({"run_id": run_id, "status": "started"}), 201


@api_bp.route("/runs/<run_id>", methods=["DELETE"])
def delete_run(run_id):
    from graybench.db import runs_db
    if runs_db.delete_run(run_id):
        return jsonify({"deleted": True})
    return jsonify({"error": "Run not found"}), 404


# ─── Models ──────────────────────────────────────────────────────────────────

@api_bp.route("/models", methods=["GET"])
def list_models():
    from graybench.db import models_db
    provider = request.args.get("provider")
    models = models_db.list_models(provider=provider)
    return jsonify(models)


@api_bp.route("/models", methods=["POST"])
def add_model():
    data = request.get_json()
    from graybench.db import models_db
    try:
        models_db.add_model(**data)
        return jsonify({"added": True}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@api_bp.route("/models/<provider>/<model_id>", methods=["PUT"])
def update_model(provider, model_id):
    data = request.get_json()
    from graybench.db import models_db
    if models_db.update_model(provider, model_id, **data):
        return jsonify({"updated": True})
    return jsonify({"error": "Model not found"}), 404


@api_bp.route("/models/<provider>/<model_id>", methods=["DELETE"])
def delete_model(provider, model_id):
    from graybench.db import models_db
    if models_db.remove_model(provider, model_id):
        return jsonify({"deleted": True})
    return jsonify({"error": "Model not found"}), 404


# ─── API Keys ────────────────────────────────────────────────────────────────

@api_bp.route("/keys", methods=["GET"])
def list_keys():
    from graybench.db import api_keys
    return jsonify(api_keys.list_keys())


@api_bp.route("/keys", methods=["POST"])
def set_key():
    data = request.get_json()
    provider = data.get("provider")
    key = data.get("key")
    key_name = data.get("key_name", "default")
    if not provider or not key:
        return jsonify({"error": "provider and key required"}), 400
    from graybench.db import api_keys
    api_keys.set_key(provider, key, key_name=key_name)
    return jsonify({"saved": True}), 201


@api_bp.route("/keys/<provider>", methods=["DELETE"])
def delete_key(provider):
    key_name = request.args.get("key_name", "default")
    from graybench.db import api_keys
    if api_keys.delete_key(provider, key_name):
        return jsonify({"deleted": True})
    return jsonify({"error": "Key not found"}), 404


@api_bp.route("/keys/<provider>/test", methods=["POST"])
def test_key(provider):
    from graybench.db import api_keys
    key = api_keys.get_key(provider)
    if not key:
        return jsonify({"error": f"No key found for {provider}"}), 404
    try:
        from graybench.db import models_db
        model_list = models_db.list_models(provider=provider)
        if not model_list:
            return jsonify({"error": f"No models for {provider}"}), 404
        model_string = f"{provider}/{model_list[0]['model_id']}"
        from graybench.llm.registry import get_provider
        llm = get_provider(model_string, api_key=key)
        resp = llm.generate("Say hello.", "Hello!", max_tokens=10)
        return jsonify({"ok": True, "response": resp[:100]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Benchmarks ──────────────────────────────────────────────────────────────

@api_bp.route("/benchmarks", methods=["GET"])
def list_benchmarks():
    from graybench.benchmarks.base import list_benchmarks, get_benchmark
    names = list_benchmarks()
    benchmarks = []
    for name in names:
        b = get_benchmark(name)
        benchmarks.append({
            "name": b.name(),
            "display_name": b.display_name(),
        })
    return jsonify(benchmarks)
