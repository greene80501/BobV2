from __future__ import annotations

from bob.protocol.v1.common import PROTOCOL_VERSION


def register(router) -> None:
    async def server_capabilities(ctx, params: dict):
        return {
            "server_name": "bob",
            "protocol_version": PROTOCOL_VERSION,
            "supported_protocol_versions": [PROTOCOL_VERSION],
            "methods": ctx.router.methods,
            "legacy_methods": [
                "bob.session.create",
                "bob.session.submit",
                "bob.session.interrupt",
                "bob.session.shutdown",
            ],
            "features": {
                "threads": True,
                "turns": True,
                "files": True,
                "exec": True,
                "agents": False,
                "tasks": True,
                "realtime": True,
                "dynamic_tools": True,
            },
        }

    async def config_get(ctx, params: dict):
        return {"config": {}}

    async def models_list(ctx, params: dict):
        from bob.llm.catalog import get_catalog
        from bob.llm.compatibility import (
            get_compatibility_matrix_rows,
            get_model_compatibility,
            get_picker_seed_models,
        )

        rows: dict[str, dict] = {}
        for seed in get_picker_seed_models():
            rows[seed["model_id"]] = dict(seed)

        catalog = get_catalog()
        for row in catalog.list_models(status="active") if catalog.is_populated() else []:
            compat = get_model_compatibility(row["model_id"], catalog_provider=row.get("provider"))
            merged = dict(row)
            merged["route"] = compat.route.value
            merged["support_level"] = compat.support_level.value
            rows[row["model_id"]] = {**rows.get(row["model_id"], {}), **merged}

        models = sorted(
            rows.values(),
            key=lambda row: (str(row.get("provider", "")), str(row.get("model_id", ""))),
        )
        return {
            "models": models,
            "compatibility_matrix": get_compatibility_matrix_rows(),
        }

    router.add("server.capabilities", server_capabilities)
    router.add("bob.config.get", config_get)
    router.add("bob.models.list", models_list)
