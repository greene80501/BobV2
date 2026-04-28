"""Tests for MCP multi-transport support and Skills SKILL.md parsing."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Config schema tests
# ---------------------------------------------------------------------------

class TestMcpServerConfigSchema:
    def test_stdio_explicit(self):
        from bob.config.schema import McpStdioServerConfig
        cfg = McpStdioServerConfig(command=["node", "server.js"])
        assert cfg.type == "stdio"
        assert cfg.command == ["node", "server.js"]

    def test_sse_config(self):
        from bob.config.schema import McpSseServerConfig
        cfg = McpSseServerConfig(url="http://localhost:8080/sse")
        assert cfg.type == "sse"
        assert cfg.url == "http://localhost:8080/sse"

    def test_http_config(self):
        from bob.config.schema import McpHttpServerConfig
        cfg = McpHttpServerConfig(url="http://localhost:9090/mcp")
        assert cfg.type == "http"
        assert cfg.url == "http://localhost:9090/mcp"

    def test_discriminator_from_dict_stdio(self):
        from bob.config.schema import McpStdioServerConfig
        from pydantic import TypeAdapter
        from typing import Annotated, Union
        from pydantic import Field
        from bob.config.schema import McpServerConfig
        import pydantic
        adapter = pydantic.TypeAdapter(McpServerConfig)
        cfg = adapter.validate_python({"type": "stdio", "command": ["python", "-m", "server"]})
        assert isinstance(cfg, McpStdioServerConfig)

    def test_discriminator_from_dict_sse(self):
        from bob.config.schema import McpSseServerConfig
        from bob.config.schema import McpServerConfig
        import pydantic
        adapter = pydantic.TypeAdapter(McpServerConfig)
        cfg = adapter.validate_python({"type": "sse", "url": "http://x/sse"})
        assert isinstance(cfg, McpSseServerConfig)

    def test_discriminator_from_dict_http(self):
        from bob.config.schema import McpHttpServerConfig
        from bob.config.schema import McpServerConfig
        import pydantic
        adapter = pydantic.TypeAdapter(McpServerConfig)
        cfg = adapter.validate_python({"type": "http", "url": "http://x/mcp"})
        assert isinstance(cfg, McpHttpServerConfig)

    def test_backward_compat_no_type_field(self):
        """Legacy configs without 'type' should upgrade to stdio."""
        from bob.config.schema import BobConfig, McpStdioServerConfig
        cfg = BobConfig.model_validate({
            "mcp_servers": {
                "my_server": {"command": ["node", "s.js"]}
            }
        })
        srv = cfg.mcp_servers["my_server"]
        assert isinstance(srv, McpStdioServerConfig)
        assert srv.command == ["node", "s.js"]

    def test_import_claude_mcp_field(self):
        from bob.config.schema import BobConfig
        cfg = BobConfig()
        assert cfg.import_claude_mcp is False

    def test_claude_plugins_path_field(self):
        from bob.config.schema import BobConfig
        cfg = BobConfig.model_validate({"claude_plugins_path": "/tmp/plugins"})
        assert cfg.claude_plugins_path == Path("/tmp/plugins")


# ---------------------------------------------------------------------------
# MCP client var substitution tests
# ---------------------------------------------------------------------------

class TestMcpClientVarSubstitution:
    def test_substitute_env_var(self, monkeypatch):
        from bob.mcp.client import _substitute_vars
        monkeypatch.setenv("MY_TOKEN", "secret123")
        result = _substitute_vars("Bearer ${MY_TOKEN}")
        assert result == "Bearer secret123"

    def test_substitute_missing_var_leaves_placeholder(self):
        from bob.mcp.client import _substitute_vars
        result = _substitute_vars("${NONEXISTENT_VAR_XYZ}")
        assert result == "${NONEXISTENT_VAR_XYZ}"

    def test_substitute_vars_in_dict(self, monkeypatch):
        from bob.mcp.client import _substitute_vars_in_dict
        monkeypatch.setenv("API_KEY", "key42")
        result = _substitute_vars_in_dict({"Authorization": "Bearer ${API_KEY}"})
        assert result == {"Authorization": "Bearer key42"}

    def test_substitute_nested_dict(self, monkeypatch):
        from bob.mcp.client import _substitute_vars_in_dict
        monkeypatch.setenv("HOST", "example.com")
        result = _substitute_vars_in_dict({"url": "https://${HOST}/api", "nested": {"path": "/${HOST}"}})
        assert result["url"] == "https://example.com/api"
        assert result["nested"]["path"] == "/example.com"

    def test_substitute_list_values(self, monkeypatch):
        from bob.mcp.client import _substitute_vars_in_dict
        monkeypatch.setenv("BIN", "/usr/local/bin")
        result = _substitute_vars_in_dict({"args": ["${BIN}/node", "--port", "3000"]})
        assert result["args"][0] == "/usr/local/bin/node"

    def test_server_connection_init_stdio(self):
        from bob.mcp.client import McpServerConnection
        conn = McpServerConnection(
            name="test",
            command=["node", "server.js"],
            transport="stdio",
        )
        assert conn.transport == "stdio"
        assert conn.command == ["node", "server.js"]
        assert not conn.is_connected

    def test_server_connection_init_sse(self):
        from bob.mcp.client import McpServerConnection
        conn = McpServerConnection(
            name="test-sse",
            transport="sse",
            url="http://localhost:8080/sse",
            headers={"Authorization": "Bearer tok"},
        )
        assert conn.transport == "sse"
        assert conn.url == "http://localhost:8080/sse"
        assert conn.headers == {"Authorization": "Bearer tok"}

    def test_server_connection_init_http(self):
        from bob.mcp.client import McpServerConnection
        conn = McpServerConnection(
            name="test-http",
            transport="http",
            url="http://localhost:9090/mcp",
        )
        assert conn.transport == "http"
        assert conn.url == "http://localhost:9090/mcp"


# ---------------------------------------------------------------------------
# Skills manager — SKILL.md parsing tests
# ---------------------------------------------------------------------------

class TestSkillsManagerSkillMd:
    def test_parse_skill_md_basic(self, tmp_path):
        from bob.skills.manager import SkillsManager
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: my-skill\n"
            "description: Does something cool\n"
            "user-invocable: true\n"
            "allowed-tools:\n"
            "  - Bash\n"
            "  - Read\n"
            "---\n\n"
            "Here is the skill body with $ARGUMENTS.\n",
            encoding="utf-8",
        )
        result = SkillsManager._parse_skill_md(skill_dir / "SKILL.md", skill_dir, "user")
        assert result is not None
        assert result.name == "my-skill"
        assert result.description == "Does something cool"
        assert result.user_invocable is True
        assert result.allowed_tools == ["Bash", "Read"]
        assert result.content_file == "SKILL.md"

    def test_parse_skill_md_no_frontmatter(self, tmp_path):
        from bob.skills.manager import SkillsManager
        skill_dir = tmp_path / "plain"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Just plain content.\n", encoding="utf-8")
        result = SkillsManager._parse_skill_md(skill_dir / "SKILL.md", skill_dir, "user")
        assert result is not None
        assert result.name == "plain"  # falls back to dir name

    def test_discover_finds_skill_md(self, tmp_path, monkeypatch):
        from bob.skills.manager import SkillsManager

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)
        skill_dir = skills_dir / "code-review"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: code-review\ndescription: Review code\n---\n",
            encoding="utf-8",
        )

        # Point bob_home at tmp_path so "user" scope resolves to tmp_path/skills
        manager = SkillsManager(tmp_path)
        entries = manager.discover(cwd=None)
        assert len(entries) == 1
        assert entries[0].skills[0].name == "code-review"
        assert entries[0].skills[0].content_file == "SKILL.md"

    def test_discover_finds_skill_toml(self, tmp_path):
        from bob.skills.manager import SkillsManager

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)
        skill_dir = skills_dir / "my-tool"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(
            '[tool]\nname = "my-tool"\ndescription = "A native skill"\n',
            encoding="utf-8",
        )
        (skill_dir / "skill.md").write_text("Do $ARGUMENTS\n", encoding="utf-8")

        manager = SkillsManager(tmp_path)
        entries = manager.discover()
        names = [s.name for e in entries for s in e.skills]
        assert "my-tool" in names

    def test_skill_toml_new_fields(self, tmp_path):
        from bob.skills.manager import SkillsManager

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)
        skill_dir = skills_dir / "invoke-me"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(
            'name = "invoke-me"\n'
            'description = "Invocable skill"\n'
            'user_invocable = true\n'
            'allowed_tools = ["Bash", "Read"]\n',
            encoding="utf-8",
        )

        manager = SkillsManager(tmp_path)
        skill = manager.find("invoke-me")
        assert skill is not None
        assert skill.user_invocable is True
        assert skill.allowed_tools == ["Bash", "Read"]
        assert skill.content_file == "skill.md"

    def test_extra_skills_are_listed_and_findable(self, tmp_path):
        from bob.protocol.items import SkillMetadata
        from bob.skills.manager import SkillsManager

        manager = SkillsManager(tmp_path)
        plugin_skill_dir = tmp_path / "plugins" / "demo" / "skills" / "reviewer"
        plugin_skill_dir.mkdir(parents=True)
        extra = SkillMetadata(
            name="reviewer",
            description="Plugin skill",
            path=plugin_skill_dir,
            scope="plugin",
            content_file="SKILL.md",
        )

        manager.set_extra_skills([extra])
        names = [skill.name for skill in manager.list_all()]
        assert "reviewer" in names
        found = manager.find("reviewer")
        assert found is not None
        assert found.scope == "plugin"


# ---------------------------------------------------------------------------
# Plugins manager — Claude Code plugin loading tests
# ---------------------------------------------------------------------------

class TestPluginsManagerClaudeCode:
    def test_list_plugins_supports_codex_manifest(self, tmp_path):
        from bob.plugins.manager import PluginsManager

        plugin_dir = tmp_path / "github-helper"
        (plugin_dir / ".codex-plugin").mkdir(parents=True)
        (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({
                "name": "github-helper",
                "version": "1.2.3",
                "description": "A codex style plugin",
            }),
            encoding="utf-8",
        )

        pm = PluginsManager(tmp_path)
        plugins = pm.list_plugins()
        assert len(plugins) == 1
        assert plugins[0].name == "github-helper"
        assert plugins[0].version == "1.2.3"

    def test_parse_mcp_json_schema_a(self, tmp_path):
        """Schema A: {"server": {...}}"""
        from bob.plugins.manager import PluginsManager
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "server": {
                "command": "node",
                "args": ["dist/index.js"],
                "env": {"API_KEY": "test"},
            }
        }), encoding="utf-8")
        cfgs = PluginsManager._parse_mcp_json(mcp_json, "my-plugin")
        assert len(cfgs) == 1
        assert cfgs[0].transport == "stdio"
        assert cfgs[0].command == ["node"]
        assert cfgs[0].args == ["dist/index.js"]

    def test_parse_mcp_json_schema_b(self, tmp_path):
        """Schema B: {"mcpServers": {"name": {...}}}"""
        from bob.plugins.manager import PluginsManager
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "server-a": {"command": "node", "args": ["a.js"]},
                "server-b": {"type": "sse", "url": "http://localhost/sse"},
            }
        }), encoding="utf-8")
        cfgs = PluginsManager._parse_mcp_json(mcp_json, "plugin")
        assert len(cfgs) == 2
        transports = {c.server_name: c.transport for c in cfgs}
        assert transports["server-a"] == "stdio"
        assert transports["server-b"] == "sse"

    def test_parse_mcp_json_sse(self, tmp_path):
        from bob.plugins.manager import PluginsManager
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "my-sse": {"type": "sse", "url": "http://host/events", "headers": {"X-Token": "abc"}}
            }
        }), encoding="utf-8")
        cfgs = PluginsManager._parse_mcp_json(mcp_json, "p")
        assert cfgs[0].transport == "sse"
        assert cfgs[0].url == "http://host/events"
        assert cfgs[0].headers == {"X-Token": "abc"}

    def test_parse_mcp_json_http(self, tmp_path):
        from bob.plugins.manager import PluginsManager
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "my-http": {"type": "http", "url": "http://host/mcp"}
            }
        }), encoding="utf-8")
        cfgs = PluginsManager._parse_mcp_json(mcp_json, "p")
        assert cfgs[0].transport == "http"

    def test_parse_mcp_json_var_substitution(self, tmp_path, monkeypatch):
        from bob.plugins.manager import PluginsManager
        monkeypatch.setenv("SECRET_TOKEN", "tok123")
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "server": {
                "command": "${CLAUDE_PLUGIN_ROOT}/run.sh",
                "env": {"TOKEN": "${SECRET_TOKEN}"},
            }
        }), encoding="utf-8")
        cfgs = PluginsManager._parse_mcp_json(mcp_json, "p")
        assert str(tmp_path) in cfgs[0].command[0]
        assert cfgs[0].env.get("TOKEN") == "tok123"

    def test_parse_mcp_json_bob_python_substitution(self, tmp_path):
        import sys
        from bob.plugins.manager import PluginsManager

        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "server": {
                "command": "${BOB_PYTHON}",
                "args": ["server.py"],
            }
        }), encoding="utf-8")
        cfgs = PluginsManager._parse_mcp_json(mcp_json, "p")
        assert cfgs[0].command == [sys.executable]

    def test_parse_skill_md(self, tmp_path):
        from bob.plugins.manager import PluginsManager
        skill_dir = tmp_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: my-skill\n"
            "description: A test skill\n"
            "user-invocable: true\n"
            "---\nDo $ARGUMENTS\n",
            encoding="utf-8",
        )
        info = PluginsManager._parse_skill_md(skill_dir / "SKILL.md", "plugin-name")
        assert info is not None
        assert info.name == "my-skill"
        assert info.user_invocable is True
        assert info.plugin_name == "plugin-name"

    def test_load_claude_code_plugins(self, tmp_path):
        from bob.plugins.manager import PluginsManager

        plugins_dir = tmp_path / "plugins"
        plugin_dir = plugins_dir / "test-plugin"
        plugin_dir.mkdir(parents=True)

        (plugin_dir / ".mcp.json").write_text(json.dumps({
            "mcpServers": {
                "test-server": {"command": "node", "args": ["server.js"]}
            }
        }), encoding="utf-8")
        (plugin_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: Test\n---\n",
            encoding="utf-8",
        )

        pm = PluginsManager(tmp_path / "bob-plugins")
        mcp_cfgs, skill_infos = pm.load_claude_code_plugins(plugins_dir)

        assert len(mcp_cfgs) == 1
        assert mcp_cfgs[0].server_name == "test-server"
        assert len(skill_infos) == 1
        assert skill_infos[0].name == "test-skill"

    def test_load_claude_code_plugins_empty_dir(self, tmp_path):
        from bob.plugins.manager import PluginsManager
        pm = PluginsManager(tmp_path / "bob-plugins")
        mcp_cfgs, skill_infos = pm.load_claude_code_plugins(tmp_path / "nonexistent")
        assert mcp_cfgs == []
        assert skill_infos == []

    def test_load_plugin_bundles_from_roots(self, tmp_path):
        from bob.plugins.manager import PluginsManager

        plugins_root = tmp_path / "plugins"
        plugin_dir = plugins_root / "repo-helper"
        (plugin_dir / "skills" / "repo-orienter").mkdir(parents=True)
        (plugin_dir / "plugin.toml").write_text(
            'name = "repo-helper"\nversion = "0.1.0"\ndescription = "Local plugin"\n',
            encoding="utf-8",
        )
        (plugin_dir / ".mcp.json").write_text(json.dumps({
            "mcpServers": {
                "repo_inspector": {
                    "command": "python",
                    "args": ["server.py"],
                }
            }
        }), encoding="utf-8")
        (plugin_dir / "skills" / "repo-orienter" / "SKILL.md").write_text(
            "---\nname: repo-orienter\ndescription: orient\n---\n",
            encoding="utf-8",
        )

        mcp_cfgs, skill_infos = PluginsManager.load_plugin_bundles_from_roots([plugins_root])
        assert len(mcp_cfgs) == 1
        assert mcp_cfgs[0].server_name == "repo_inspector"
        assert len(skill_infos) == 1
        assert skill_infos[0].name == "repo-orienter"


# ---------------------------------------------------------------------------
# Config loader — Claude settings import tests
# ---------------------------------------------------------------------------

class TestLoadClaudeSettings:
    def test_load_empty_when_no_file(self, tmp_path, monkeypatch):
        from bob.config.loader import _load_claude_settings
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        result = _load_claude_settings()
        assert result == {}

    def test_load_stdio_server(self, tmp_path, monkeypatch):
        from bob.config.loader import _load_claude_settings
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / "settings.json").write_text(json.dumps({
            "mcpServers": {
                "my-server": {
                    "command": "node",
                    "args": ["server.js"],
                    "env": {"KEY": "val"},
                }
            }
        }), encoding="utf-8")
        result = _load_claude_settings()
        assert "mcp_servers" in result
        assert "my-server" in result["mcp_servers"]
        srv = result["mcp_servers"]["my-server"]
        assert srv["type"] == "stdio"
        assert "node" in srv["command"]

    def test_load_sse_server(self, tmp_path, monkeypatch):
        from bob.config.loader import _load_claude_settings
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / "settings.json").write_text(json.dumps({
            "mcpServers": {
                "sse-srv": {"type": "sse", "url": "http://localhost/sse"}
            }
        }), encoding="utf-8")
        result = _load_claude_settings()
        assert result["mcp_servers"]["sse-srv"]["type"] == "sse"

    def test_desktop_config_fallback(self, tmp_path, monkeypatch):
        from bob.config.loader import _load_claude_settings
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / "claude_desktop_config.json").write_text(json.dumps({
            "mcpServers": {
                "desktop-srv": {"command": "python", "args": ["-m", "server"]}
            }
        }), encoding="utf-8")
        result = _load_claude_settings()
        assert "desktop-srv" in result["mcp_servers"]


# ---------------------------------------------------------------------------
# ToolRegistry — unregister_by_source tests
# ---------------------------------------------------------------------------

class TestToolRegistryUnregisterBySource:
    def test_unregister_by_source_removes_matching(self):
        from bob.tools.registry import ToolRegistry

        async def noop(tc, args):
            return "ok"

        r = ToolRegistry()
        r.register("tool_a", "desc", {"type": "object"}, noop, source="mcp")
        r.register("tool_b", "desc", {"type": "object"}, noop, source="mcp")
        r.register("tool_c", "desc", {"type": "object"}, noop, source="core")

        count = r.unregister_by_source("mcp")
        assert count == 2
        assert not r.has_tool("tool_a")
        assert not r.has_tool("tool_b")
        assert r.has_tool("tool_c")

    def test_unregister_by_source_empty(self):
        from bob.tools.registry import ToolRegistry
        r = ToolRegistry()
        count = r.unregister_by_source("mcp")
        assert count == 0
