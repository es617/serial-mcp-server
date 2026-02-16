"""Plugin loader and manager for Serial MCP server.

Loads user plugins from `.serial_mcp/plugins/`. No serial imports.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.types import Tool

logger = logging.getLogger(__name__)

RESERVED_NAMES = frozenset({"all"})


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def parse_plugin_policy() -> tuple[bool, set[str] | None]:
    """Parse ``SERIAL_MCP_PLUGINS`` env var.

    Returns ``(enabled, allowlist)``:
    - unset/empty → ``(False, None)`` — plugins disabled
    - ``*``       → ``(True, None)``  — all plugins allowed
    - ``a,b``     → ``(True, {"a", "b"})`` — only named plugins
    """
    raw = os.environ.get("SERIAL_MCP_PLUGINS", "").strip()
    if not raw:
        return False, None
    if raw in ("*", "all"):
        return True, None
    names = {n.strip() for n in raw.split(",") if n.strip()}
    return (True, names) if names else (False, None)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class PluginInfo:
    name: str
    path: Path
    tool_names: list[str]
    module_key: str
    meta: dict[str, Any]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_plugin(plugin_path: Path) -> tuple[str, list[Tool], dict[str, Any], str, dict[str, Any]]:
    """Load a single plugin file/package and validate its exports.

    Returns ``(name, tools, handlers, module_key)``.
    Raises ``ValueError`` on any validation failure.
    """
    resolved = plugin_path.resolve()

    if resolved.is_dir():
        name = resolved.name
        entry = resolved / "__init__.py"
        if not entry.exists():
            raise ValueError(f"Plugin directory {resolved} has no __init__.py")
    elif resolved.is_file() and resolved.suffix == ".py":
        name = resolved.stem
        entry = resolved
    else:
        raise ValueError(f"Not a valid plugin path: {plugin_path}")

    if name in RESERVED_NAMES:
        raise ValueError(f"Plugin name '{name}' is reserved")

    path_hash = hashlib.sha256(str(resolved).encode()).hexdigest()[:12]
    module_key = f"serial_mcp_plugin__{name}__{path_hash}"

    # Remove stale module if present
    sys.modules.pop(module_key, None)

    spec = importlib.util.spec_from_file_location(module_key, str(entry))
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot create module spec for {entry}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_key] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_key, None)
        raise ValueError(f"Error executing plugin {name}: {exc}") from exc

    # --- Validate exports ---
    tools = getattr(module, "TOOLS", None)
    handlers = getattr(module, "HANDLERS", None)

    if not isinstance(tools, list):
        sys.modules.pop(module_key, None)
        raise ValueError(f"Plugin {name}: TOOLS must be a list, got {type(tools)}")
    if not isinstance(handlers, dict):
        sys.modules.pop(module_key, None)
        raise ValueError(f"Plugin {name}: HANDLERS must be a dict, got {type(handlers)}")

    tool_names = {t.name for t in tools}
    handler_names = set(handlers.keys())

    if tool_names != handler_names:
        sys.modules.pop(module_key, None)
        only_tools = tool_names - handler_names
        only_handlers = handler_names - tool_names
        parts = []
        if only_tools:
            parts.append(f"tools without handlers: {only_tools}")
        if only_handlers:
            parts.append(f"handlers without tools: {only_handlers}")
        raise ValueError(f"Plugin {name}: TOOLS/HANDLERS mismatch — {', '.join(parts)}")

    meta = getattr(module, "META", {})
    if not isinstance(meta, dict):
        meta = {}

    return name, tools, handlers, module_key, meta


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_plugins(plugins_dir: Path) -> list[Path]:
    """Find loadable plugins in *plugins_dir*.

    - ``.py`` files (excluding ``__init__.py``) → path to the file
    - Subdirs containing ``__init__.py`` → path to the subdir
    - Ignores ``__pycache__`` and dotfiles/dotdirs.
    """
    if not plugins_dir.is_dir():
        return []

    results: list[Path] = []
    for child in sorted(plugins_dir.iterdir()):
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        if (child.is_file() and child.suffix == ".py" and child.name != "__init__.py") or (
            child.is_dir() and (child / "__init__.py").exists()
        ):
            results.append(child)

    return results


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class PluginManager:
    """Manages loading, unloading, and reloading of plugins."""

    def __init__(
        self,
        plugins_dir: Path,
        tools: list[Tool],
        handlers: dict[str, Any],
        *,
        enabled: bool = False,
        allowlist: set[str] | None = None,
    ) -> None:
        self.plugins_dir = plugins_dir
        self._tools = tools
        self._handlers = handlers
        self.enabled = enabled
        self.allowlist = allowlist
        self.loaded: dict[str, PluginInfo] = {}

    @property
    def policy(self) -> str:
        """Human-readable policy string."""
        if not self.enabled:
            return "disabled"
        if self.allowlist is None:
            return "*"
        return ",".join(sorted(self.allowlist))

    def _check_allowed(self, name: str) -> None:
        """Raise ``PermissionError`` if the plugin is not allowed by policy."""
        if not self.enabled:
            raise PermissionError(
                "Plugins are disabled. Set SERIAL_MCP_PLUGINS=all or SERIAL_MCP_PLUGINS=name1,name2 to enable."
            )
        if self.allowlist is not None and name not in self.allowlist:
            raise PermissionError(
                f"Plugin '{name}' is not in the allowlist (SERIAL_MCP_PLUGINS={self.policy})."
            )

    @staticmethod
    def _plugin_name_from_path(plugin_path: Path) -> str:
        """Derive the plugin name from a path without executing any code."""
        resolved = plugin_path.resolve()
        if resolved.is_dir():
            return resolved.name
        return resolved.stem

    def load(self, plugin_path: Path) -> PluginInfo:
        """Load a plugin and register its tools/handlers.

        Raises ``PermissionError`` if blocked by policy,
        ``ValueError`` on path traversal, name collision, or validation failure.
        """
        resolved = plugin_path.resolve()
        plugins_root = self.plugins_dir.resolve()
        if plugins_root not in resolved.parents and resolved != plugins_root:
            raise ValueError(f"Plugin path must be inside {self.plugins_dir}/ — got {plugin_path}")

        # Check policy BEFORE executing any plugin code
        self._check_allowed(self._plugin_name_from_path(plugin_path))

        name, tools, handlers, module_key, meta = load_plugin(plugin_path)

        # If already loaded, unload first (makes load idempotent)
        if name in self.loaded:
            logger.info("Plugin %s already loaded — reloading", name)
            self.unload(name)

        # Check for name collisions
        existing_names = {t.name for t in self._tools}
        for tool in tools:
            if tool.name in existing_names:
                # Clean up the module we just loaded
                sys.modules.pop(module_key, None)
                raise ValueError(f"Plugin {name}: tool '{tool.name}' collides with an existing tool")

        self._tools.extend(tools)
        self._handlers.update(handlers)
        info = PluginInfo(
            name=name,
            path=plugin_path.resolve(),
            tool_names=[t.name for t in tools],
            module_key=module_key,
            meta=meta,
        )
        self.loaded[name] = info
        logger.info("Loaded plugin %s with tools: %s", name, info.tool_names)
        return info

    def unload(self, name: str) -> None:
        """Unload a plugin by name.

        Raises ``KeyError`` if the plugin is not loaded.
        """
        if name not in self.loaded:
            raise KeyError(f"Plugin not loaded: {name}")

        info = self.loaded[name]
        names_to_remove = set(info.tool_names)

        # Filter tools list in-place
        self._tools[:] = [t for t in self._tools if t.name not in names_to_remove]

        # Remove handlers
        for tool_name in info.tool_names:
            self._handlers.pop(tool_name, None)

        # Clean up module
        sys.modules.pop(info.module_key, None)

        del self.loaded[name]
        logger.info("Unloaded plugin %s", name)

    def reload(self, name: str) -> PluginInfo:
        """Reload a plugin by name (unload then load).

        Raises ``KeyError`` if the plugin is not loaded.
        """
        if name not in self.loaded:
            raise KeyError(f"Plugin not loaded: {name}")

        path = self.loaded[name].path
        self.unload(name)
        return self.load(path)

    def load_all(self) -> None:
        """Discover and load all plugins, logging errors but continuing.

        Skips silently when plugins are disabled.
        """
        if not self.enabled:
            return
        paths = discover_plugins(self.plugins_dir)
        for path in paths:
            try:
                self.load(path)
            except Exception as exc:
                logger.error("Failed to load plugin %s: %s", path, exc)
