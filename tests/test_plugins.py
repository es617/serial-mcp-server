"""Tests for serial_mcp_server.plugins — no serial hardware required."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import Tool

from serial_mcp_server.plugins import PluginManager, discover_plugins, load_plugin, parse_plugin_policy

# ---------------------------------------------------------------------------
# Helpers — write plugin files into tmp_path
# ---------------------------------------------------------------------------


def _write_plugin(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


VALID_PLUGIN = """\
from mcp.types import Tool

TOOLS = [
    Tool(
        name="test.hello",
        description="Say hello",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
]

async def _handle(state, args):
    return {"ok": True, "message": "hello"}

HANDLERS = {"test.hello": _handle}
"""

VALID_PLUGIN_V2 = """\
from mcp.types import Tool

TOOLS = [
    Tool(
        name="test.hello",
        description="Say hello v2",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
]

async def _handle(state, args):
    return {"ok": True, "message": "hello v2"}

HANDLERS = {"test.hello": _handle}
"""

MULTI_TOOL_PLUGIN = """\
from mcp.types import Tool

TOOLS = [
    Tool(name="test.a", description="A", inputSchema={"type": "object", "properties": {}, "required": []}),
    Tool(name="test.b", description="B", inputSchema={"type": "object", "properties": {}, "required": []}),
]

async def _a(state, args):
    return {"ok": True}

async def _b(state, args):
    return {"ok": True}

HANDLERS = {"test.a": _a, "test.b": _b}
"""


# ---------------------------------------------------------------------------
# discover_plugins
# ---------------------------------------------------------------------------


class TestDiscoverPlugins:
    def test_finds_py_files_and_package_dirs(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        _write_plugin(plugins_dir / "alpha.py", VALID_PLUGIN)
        _write_plugin(plugins_dir / "beta.py", VALID_PLUGIN)
        pkg = plugins_dir / "gamma"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(VALID_PLUGIN)

        result = discover_plugins(plugins_dir)
        names = [p.name for p in result]
        assert names == ["alpha.py", "beta.py", "gamma"]

    def test_ignores_pycache_and_dotfiles(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        _write_plugin(plugins_dir / "good.py", VALID_PLUGIN)
        (plugins_dir / "__pycache__").mkdir()
        (plugins_dir / ".hidden.py").write_text("# hidden")
        (plugins_dir / "__init__.py").write_text("# top-level init")

        result = discover_plugins(plugins_dir)
        assert [p.name for p in result] == ["good.py"]

    def test_ignores_dirs_without_init(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "nopkg").mkdir()
        (plugins_dir / "nopkg" / "something.py").write_text("x = 1")

        assert discover_plugins(plugins_dir) == []

    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        assert discover_plugins(tmp_path / "nonexistent") == []


# ---------------------------------------------------------------------------
# load_plugin
# ---------------------------------------------------------------------------


class TestLoadPlugin:
    def test_valid_single_file(self, tmp_path: Path) -> None:
        path = _write_plugin(tmp_path / "hello.py", VALID_PLUGIN)
        name, tools, handlers, module_key, meta = load_plugin(path)

        assert name == "hello"
        assert len(tools) == 1
        assert tools[0].name == "test.hello"
        assert "test.hello" in handlers
        assert module_key.startswith("serial_mcp_plugin__hello__")
        # Clean up
        sys.modules.pop(module_key, None)

    def test_valid_package(self, tmp_path: Path) -> None:
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(VALID_PLUGIN)

        name, tools, handlers, module_key, meta = load_plugin(pkg)
        assert name == "mypkg"
        assert len(tools) == 1
        sys.modules.pop(module_key, None)

    def test_raises_on_missing_tools(self, tmp_path: Path) -> None:
        path = _write_plugin(tmp_path / "bad.py", "HANDLERS = {}")
        with pytest.raises(ValueError, match="TOOLS must be a list"):
            load_plugin(path)

    def test_raises_on_missing_handlers(self, tmp_path: Path) -> None:
        content = """\
from mcp.types import Tool
TOOLS = [Tool(name="x", description="x", inputSchema={"type": "object", "properties": {}, "required": []})]
"""
        path = _write_plugin(tmp_path / "bad2.py", content)
        with pytest.raises(ValueError, match="HANDLERS must be a dict"):
            load_plugin(path)

    def test_raises_on_name_mismatch(self, tmp_path: Path) -> None:
        content = """\
from mcp.types import Tool
TOOLS = [Tool(name="a", description="a", inputSchema={"type": "object", "properties": {}, "required": []})]
async def _h(state, args): return {}
HANDLERS = {"b": _h}
"""
        path = _write_plugin(tmp_path / "mismatch.py", content)
        with pytest.raises(ValueError, match="TOOLS/HANDLERS mismatch"):
            load_plugin(path)

    def test_unique_module_key(self, tmp_path: Path) -> None:
        p1 = _write_plugin(tmp_path / "dir1" / "hello.py", VALID_PLUGIN)
        p2 = _write_plugin(tmp_path / "dir2" / "hello.py", VALID_PLUGIN)

        _, _, _, key1, _ = load_plugin(p1)
        _, _, _, key2, _ = load_plugin(p2)

        assert key1 != key2
        assert key1.startswith("serial_mcp_plugin__hello__")
        assert key2.startswith("serial_mcp_plugin__hello__")
        sys.modules.pop(key1, None)
        sys.modules.pop(key2, None)

    def test_raises_on_dir_without_init(self, tmp_path: Path) -> None:
        pkg = tmp_path / "noinit"
        pkg.mkdir()
        with pytest.raises(ValueError, match=r"no __init__\.py"):
            load_plugin(pkg)

    def test_meta_returned_when_present(self, tmp_path: Path) -> None:
        content = VALID_PLUGIN + '\nMETA = {"description": "Test plugin", "service_uuids": ["180a"]}\n'
        path = _write_plugin(tmp_path / "withmeta.py", content)
        name, tools, handlers, module_key, meta = load_plugin(path)
        assert meta == {"description": "Test plugin", "service_uuids": ["180a"]}
        sys.modules.pop(module_key, None)

    def test_meta_defaults_to_empty_dict(self, tmp_path: Path) -> None:
        path = _write_plugin(tmp_path / "nometa.py", VALID_PLUGIN)
        name, tools, handlers, module_key, meta = load_plugin(path)
        assert meta == {}
        sys.modules.pop(module_key, None)

    def test_raises_on_reserved_name(self, tmp_path: Path) -> None:
        path = _write_plugin(tmp_path / "all.py", VALID_PLUGIN)
        with pytest.raises(ValueError, match="reserved"):
            load_plugin(path)

    def test_raises_on_syntax_error(self, tmp_path: Path) -> None:
        path = _write_plugin(tmp_path / "broken.py", "def oops(:\n  pass\n")
        with pytest.raises(ValueError, match="Error executing plugin"):
            load_plugin(path)


# ---------------------------------------------------------------------------
# PluginManager
# ---------------------------------------------------------------------------


class TestPluginManager:
    def _make_manager(
        self,
        tmp_path: Path,
        *,
        enabled: bool = True,
        allowlist: set[str] | None = None,
    ) -> tuple[PluginManager, list[Tool], dict[str, Any]]:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir(exist_ok=True)
        tools: list[Tool] = [
            Tool(
                name="core.tool",
                description="core",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
        ]
        handlers: dict[str, Any] = {"core.tool": lambda s, a: None}
        manager = PluginManager(plugins_dir, tools, handlers, enabled=enabled, allowlist=allowlist)
        return manager, tools, handlers

    def test_load_adds_tools_and_handlers(self, tmp_path: Path) -> None:
        manager, tools, handlers = self._make_manager(tmp_path)
        path = _write_plugin(manager.plugins_dir / "hello.py", VALID_PLUGIN)

        info = manager.load(path)

        assert info.name == "hello"
        assert "test.hello" in info.tool_names
        assert any(t.name == "test.hello" for t in tools)
        assert "test.hello" in handlers
        assert "hello" in manager.loaded

    def test_load_raises_on_name_collision(self, tmp_path: Path) -> None:
        manager, tools, handlers = self._make_manager(tmp_path)
        # Plugin that tries to register "core.tool" which already exists
        content = """\
from mcp.types import Tool
TOOLS = [Tool(name="core.tool", description="collision", inputSchema={"type": "object", "properties": {}, "required": []})]
async def _h(state, args): return {}
HANDLERS = {"core.tool": _h}
"""
        path = _write_plugin(manager.plugins_dir / "collider.py", content)

        with pytest.raises(ValueError, match="collides with an existing tool"):
            manager.load(path)

        # Original tool should still be there
        assert len([t for t in tools if t.name == "core.tool"]) == 1

    def test_load_raises_on_plugin_collision(self, tmp_path: Path) -> None:
        manager, tools, handlers = self._make_manager(tmp_path)
        path = _write_plugin(manager.plugins_dir / "hello.py", VALID_PLUGIN)
        manager.load(path)

        # Second plugin with same tool name
        content = """\
from mcp.types import Tool
TOOLS = [Tool(name="test.hello", description="dup", inputSchema={"type": "object", "properties": {}, "required": []})]
async def _h(state, args): return {}
HANDLERS = {"test.hello": _h}
"""
        path2 = _write_plugin(manager.plugins_dir / "dup.py", content)
        with pytest.raises(ValueError, match="collides with an existing tool"):
            manager.load(path2)

    def test_unload_removes_tools_and_handlers(self, tmp_path: Path) -> None:
        manager, tools, handlers = self._make_manager(tmp_path)
        path = _write_plugin(manager.plugins_dir / "hello.py", VALID_PLUGIN)
        info = manager.load(path)

        manager.unload("hello")

        assert not any(t.name == "test.hello" for t in tools)
        assert "test.hello" not in handlers
        assert "hello" not in manager.loaded
        assert info.module_key not in sys.modules

    def test_unload_raises_for_unknown(self, tmp_path: Path) -> None:
        manager, _, _ = self._make_manager(tmp_path)
        with pytest.raises(KeyError, match="Plugin not loaded"):
            manager.unload("nonexistent")

    def test_reload_swaps_tools(self, tmp_path: Path) -> None:
        manager, tools, handlers = self._make_manager(tmp_path)
        path = _write_plugin(manager.plugins_dir / "hello.py", VALID_PLUGIN)
        manager.load(path)

        # Overwrite with v2
        path.write_text(VALID_PLUGIN_V2)
        info = manager.reload("hello")

        assert info.name == "hello"
        # Should have one test.hello tool with v2 description
        plugin_tools = [t for t in tools if t.name == "test.hello"]
        assert len(plugin_tools) == 1
        assert "v2" in plugin_tools[0].description

    def test_load_all_discovers_and_loads(self, tmp_path: Path) -> None:
        manager, tools, handlers = self._make_manager(tmp_path)
        _write_plugin(manager.plugins_dir / "alpha.py", VALID_PLUGIN.replace("test.hello", "test.alpha"))
        _write_plugin(manager.plugins_dir / "beta.py", MULTI_TOOL_PLUGIN)

        manager.load_all()

        assert "alpha" in manager.loaded
        assert "beta" in manager.loaded
        assert "test.alpha" in handlers
        assert "test.a" in handlers
        assert "test.b" in handlers

    def test_load_rejects_path_outside_plugins_dir(self, tmp_path: Path) -> None:
        manager, tools, handlers = self._make_manager(tmp_path)
        # Write a valid plugin *outside* the plugins dir
        outside = _write_plugin(tmp_path / "elsewhere" / "evil.py", VALID_PLUGIN)

        with pytest.raises(ValueError, match="must be inside"):
            manager.load(outside)

        assert "evil" not in manager.loaded
        assert not any(t.name == "test.hello" for t in tools)

    def test_load_rejects_traversal_path(self, tmp_path: Path) -> None:
        manager, tools, handlers = self._make_manager(tmp_path)
        # Write a valid plugin inside plugins dir but reference via traversal
        _write_plugin(tmp_path / "elsewhere" / "sneaky.py", VALID_PLUGIN)
        traversal_path = manager.plugins_dir / ".." / "elsewhere" / "sneaky.py"

        with pytest.raises(ValueError, match="must be inside"):
            manager.load(traversal_path)

    def test_load_all_logs_errors_continues(self, tmp_path: Path) -> None:
        manager, tools, handlers = self._make_manager(tmp_path)
        # One bad, one good
        _write_plugin(manager.plugins_dir / "bad.py", "# no TOOLS or HANDLERS")
        _write_plugin(manager.plugins_dir / "good.py", VALID_PLUGIN)

        manager.load_all()

        assert "good" in manager.loaded
        assert "bad" not in manager.loaded


# ---------------------------------------------------------------------------
# handlers_plugin (list handler)
# ---------------------------------------------------------------------------


class TestPluginListHandler:
    @pytest.mark.asyncio
    async def test_returns_loaded_plugins(self, tmp_path: Path) -> None:
        from serial_mcp_server.handlers_plugin import make_handlers

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        tools: list[Tool] = []
        handlers: dict[str, Any] = {}
        manager = PluginManager(plugins_dir, tools, handlers, enabled=True)
        _write_plugin(plugins_dir / "hello.py", VALID_PLUGIN)
        manager.load(plugins_dir / "hello.py")

        # Use a dummy server (list handler doesn't use it)
        plugin_handlers = make_handlers(manager, None)  # type: ignore[arg-type]
        result = await plugin_handlers["serial.plugin.list"](None, {})

        assert result["ok"] is True
        assert result["count"] == 1
        assert result["plugins"][0]["name"] == "hello"
        assert "test.hello" in result["plugins"][0]["tools"]
        assert result["plugins_dir"] == str(plugins_dir)

    @pytest.mark.asyncio
    async def test_returns_empty_when_none_loaded(self, tmp_path: Path) -> None:
        from serial_mcp_server.handlers_plugin import make_handlers

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        tools: list[Tool] = []
        handlers: dict[str, Any] = {}
        manager = PluginManager(plugins_dir, tools, handlers, enabled=True)

        plugin_handlers = make_handlers(manager, None)  # type: ignore[arg-type]
        result = await plugin_handlers["serial.plugin.list"](None, {})

        assert result["ok"] is True
        assert result["count"] == 0
        assert result["plugins"] == []
        assert result["plugins_dir"] == str(plugins_dir)


# ---------------------------------------------------------------------------
# parse_plugin_policy
# ---------------------------------------------------------------------------


class TestParsePluginPolicy:
    def test_unset_returns_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SERIAL_MCP_PLUGINS", raising=False)
        enabled, allowlist = parse_plugin_policy()
        assert enabled is False
        assert allowlist is None

    def test_empty_returns_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERIAL_MCP_PLUGINS", "")
        enabled, allowlist = parse_plugin_policy()
        assert enabled is False

    def test_star_returns_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERIAL_MCP_PLUGINS", "*")
        enabled, allowlist = parse_plugin_policy()
        assert enabled is True
        assert allowlist is None

    def test_all_returns_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERIAL_MCP_PLUGINS", "all")
        enabled, allowlist = parse_plugin_policy()
        assert enabled is True
        assert allowlist is None

    def test_csv_returns_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERIAL_MCP_PLUGINS", "sensortag, hello")
        enabled, allowlist = parse_plugin_policy()
        assert enabled is True
        assert allowlist == {"sensortag", "hello"}

    def test_whitespace_only_returns_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERIAL_MCP_PLUGINS", "   ")
        enabled, allowlist = parse_plugin_policy()
        assert enabled is False

    def test_empty_commas_returns_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERIAL_MCP_PLUGINS", ",,,")
        enabled, allowlist = parse_plugin_policy()
        assert enabled is False
        assert allowlist is None


# ---------------------------------------------------------------------------
# PluginManager — policy enforcement
# ---------------------------------------------------------------------------


class TestPluginManagerPolicy:
    def _make_manager(
        self,
        tmp_path: Path,
        *,
        enabled: bool = False,
        allowlist: set[str] | None = None,
    ) -> tuple[PluginManager, list[Tool], dict[str, Any]]:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir(exist_ok=True)
        tools: list[Tool] = []
        handlers: dict[str, Any] = {}
        manager = PluginManager(plugins_dir, tools, handlers, enabled=enabled, allowlist=allowlist)
        return manager, tools, handlers

    def test_load_disabled_raises(self, tmp_path: Path) -> None:
        manager, _, _ = self._make_manager(tmp_path, enabled=False)
        path = _write_plugin(manager.plugins_dir / "hello.py", VALID_PLUGIN)

        with pytest.raises(PermissionError, match="Plugins are disabled"):
            manager.load(path)

    def test_load_not_in_allowlist_raises(self, tmp_path: Path) -> None:
        manager, _, _ = self._make_manager(tmp_path, enabled=True, allowlist={"other"})
        path = _write_plugin(manager.plugins_dir / "hello.py", VALID_PLUGIN)

        with pytest.raises(PermissionError, match="not in the allowlist"):
            manager.load(path)

    def test_load_in_allowlist_succeeds(self, tmp_path: Path) -> None:
        manager, tools, handlers = self._make_manager(tmp_path, enabled=True, allowlist={"hello"})
        path = _write_plugin(manager.plugins_dir / "hello.py", VALID_PLUGIN)

        info = manager.load(path)
        assert info.name == "hello"
        assert "test.hello" in handlers

    def test_load_all_skips_when_disabled(self, tmp_path: Path) -> None:
        manager, tools, handlers = self._make_manager(tmp_path, enabled=False)
        _write_plugin(manager.plugins_dir / "hello.py", VALID_PLUGIN)

        manager.load_all()

        assert len(manager.loaded) == 0
        assert "test.hello" not in handlers

    def test_load_all_respects_allowlist(self, tmp_path: Path) -> None:
        manager, tools, handlers = self._make_manager(tmp_path, enabled=True, allowlist={"hello"})
        _write_plugin(manager.plugins_dir / "hello.py", VALID_PLUGIN)
        _write_plugin(
            manager.plugins_dir / "blocked.py",
            VALID_PLUGIN.replace("test.hello", "test.blocked"),
        )

        manager.load_all()

        assert "hello" in manager.loaded
        assert "blocked" not in manager.loaded

    def test_policy_property_disabled(self, tmp_path: Path) -> None:
        manager, _, _ = self._make_manager(tmp_path, enabled=False)
        assert manager.policy == "disabled"

    def test_policy_property_star(self, tmp_path: Path) -> None:
        manager, _, _ = self._make_manager(tmp_path, enabled=True)
        assert manager.policy == "*"

    def test_policy_property_names(self, tmp_path: Path) -> None:
        manager, _, _ = self._make_manager(tmp_path, enabled=True, allowlist={"b", "a"})
        assert manager.policy == "a,b"


# ---------------------------------------------------------------------------
# Plugin handler tests (template, reload, load)
# ---------------------------------------------------------------------------


class TestPluginHandlers:
    """Tests for handler functions in serial_mcp_server.handlers_plugin."""

    def _setup(self, tmp_path: Path) -> tuple[Any, dict[str, Any]]:
        """Create a PluginManager with make_handlers. Returns (plugin_handlers, manager)."""
        from serial_mcp_server.handlers_plugin import make_handlers

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        tools: list[Tool] = []
        handlers: dict[str, Any] = {}
        manager = PluginManager(plugins_dir, tools, handlers, enabled=True)

        mock_server = MagicMock()
        mock_server.request_context.session.send_tool_list_changed = AsyncMock()

        plugin_handlers = make_handlers(manager, mock_server)
        return plugin_handlers, manager

    @pytest.mark.asyncio
    async def test_template_returns_template_and_path(self, tmp_path: Path) -> None:
        plugin_handlers, manager = self._setup(tmp_path)

        result = await plugin_handlers["serial.plugin.template"](None, {})
        assert result["ok"] is True
        assert "TOOLS" in result["template"]
        assert "HANDLERS" in result["template"]
        assert "suggested_path" in result

    @pytest.mark.asyncio
    async def test_template_with_device_name(self, tmp_path: Path) -> None:
        plugin_handlers, manager = self._setup(tmp_path)

        result = await plugin_handlers["serial.plugin.template"](None, {"device_name": "SensorTag"})
        assert result["ok"] is True
        assert "SensorTag" in result["template"] or "sensortag" in result["template"]
        assert "sensortag" in result["suggested_path"]

    @pytest.mark.asyncio
    async def test_reload_success(self, tmp_path: Path) -> None:
        plugin_handlers, manager = self._setup(tmp_path)

        # Load a plugin first
        path = _write_plugin(manager.plugins_dir / "hello.py", VALID_PLUGIN)
        manager.load(path)

        result = await plugin_handlers["serial.plugin.reload"](None, {"name": "hello"})
        assert result["ok"] is True
        assert result["name"] == "hello"
        assert "test.hello" in result["tools"]

    @pytest.mark.asyncio
    async def test_reload_unknown_plugin(self, tmp_path: Path) -> None:
        plugin_handlers, manager = self._setup(tmp_path)

        result = await plugin_handlers["serial.plugin.reload"](None, {"name": "nope"})
        assert result["ok"] is False
        assert result["error"]["code"] == "not_found"

    @pytest.mark.asyncio
    async def test_reload_missing_name(self, tmp_path: Path) -> None:
        plugin_handlers, manager = self._setup(tmp_path)

        result = await plugin_handlers["serial.plugin.reload"](None, {"name": ""})
        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_params"

    @pytest.mark.asyncio
    async def test_load_success(self, tmp_path: Path) -> None:
        plugin_handlers, manager = self._setup(tmp_path)

        _write_plugin(manager.plugins_dir / "hello.py", VALID_PLUGIN)

        result = await plugin_handlers["serial.plugin.load"](
            None, {"path": str(manager.plugins_dir / "hello.py")}
        )
        assert result["ok"] is True
        assert result["name"] == "hello"
        assert "test.hello" in result["tools"]

    @pytest.mark.asyncio
    async def test_load_empty_path(self, tmp_path: Path) -> None:
        plugin_handlers, manager = self._setup(tmp_path)

        result = await plugin_handlers["serial.plugin.load"](None, {"path": ""})
        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_params"

    @pytest.mark.asyncio
    async def test_load_path_traversal_blocked(self, tmp_path: Path) -> None:
        plugin_handlers, manager = self._setup(tmp_path)

        # Write plugin outside plugins dir
        _write_plugin(tmp_path / "elsewhere" / "evil.py", VALID_PLUGIN)
        traversal = str(manager.plugins_dir / ".." / "elsewhere" / "evil.py")

        result = await plugin_handlers["serial.plugin.load"](None, {"path": traversal})
        assert result["ok"] is False
        assert result["error"]["code"] == "plugin_error"

    @pytest.mark.asyncio
    async def test_list_when_plugins_disabled(self, tmp_path: Path) -> None:
        from serial_mcp_server.handlers_plugin import make_handlers

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        tools: list[Tool] = []
        handlers: dict[str, Any] = {}
        manager = PluginManager(plugins_dir, tools, handlers, enabled=False)

        plugin_handlers = make_handlers(manager, None)  # type: ignore[arg-type]
        result = await plugin_handlers["serial.plugin.list"](None, {})

        assert result["ok"] is True
        assert result["enabled"] is False
        assert result["policy"] == "disabled"
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_list_shows_policy_with_allowlist(self, tmp_path: Path) -> None:
        from serial_mcp_server.handlers_plugin import make_handlers

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        tools: list[Tool] = []
        handlers: dict[str, Any] = {}
        manager = PluginManager(
            plugins_dir,
            tools,
            handlers,
            enabled=True,
            allowlist={"alpha", "beta"},
        )

        plugin_handlers = make_handlers(manager, None)  # type: ignore[arg-type]
        result = await plugin_handlers["serial.plugin.list"](None, {})

        assert result["ok"] is True
        assert result["enabled"] is True
        assert result["policy"] == "alpha,beta"
