# Contributing

## Dev setup

```bash
# Clone and install in editable mode with test dependencies
git clone https://github.com/es617/serial-mcp-server.git
cd serial-mcp-server
pip install -e ".[test]"

# Run tests (no serial hardware needed)
python -m pytest tests/ -v
```

## How tools are registered

Each `handlers_*.py` file exports:

```python
TOOLS: list[Tool] = [...]          # Tool definitions with names, descriptions, schemas
HANDLERS: dict[str, Callable] = {  # Maps tool name → async handler function
    "serial.tool_name": handle_fn,
}
```

In `server.py`, these are merged inside `build_server()`:

```python
tools = handlers_serial.TOOLS + handlers_introspection.TOOLS + handlers_spec.TOOLS + handlers_trace.TOOLS + handlers_plugin.TOOLS
handlers = {**handlers_serial.HANDLERS, **handlers_introspection.HANDLERS, **handlers_spec.HANDLERS, **handlers_trace.HANDLERS}
```

Plugin handlers are added via `handlers_plugin.make_handlers()`, which returns closures that capture the `PluginManager` and `Server` instances.

## Handler pattern

Every handler has the same signature:

```python
async def handle_something(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
```

- `state` — shared serial state (connections)
- `args` — parsed tool arguments from the MCP client
- Returns `_ok(key=value)` on success or `_err(code, message)` on failure

The dispatcher in `server.py` catches common exceptions (KeyError, SerialException, TimeoutError, etc.) and converts them to error responses automatically.

## Adding a new tool

1. Add the `Tool(...)` definition to the appropriate `handlers_*.py` `TOOLS` list
2. Write the handler function following the signature above
3. Add the mapping to the `HANDLERS` dict
4. Add tests in the corresponding `test_*.py`

Tool names follow the convention `serial.<action>` for core tools (e.g., `serial.read`, `serial.open`) and `serial.<category>.<action>` for subsystems (e.g., `serial.spec.read`, `serial.plugin.reload`).

## Plugin system internals

**Path containment:** `PluginManager.load()` resolves the path and verifies it is inside `plugins_dir` before loading. Paths outside `.serial_mcp/plugins/` are rejected with `ValueError`.

**Loading:** `load_plugin()` uses `importlib` to load a `.py` file or package `__init__.py`. It validates `TOOLS`, `HANDLERS`, and optional `META` exports, and registers the module in `sys.modules` with a unique key (`serial_mcp_plugin__{name}__{hash}`).

**Name collisions:** If a plugin tool name collides with any existing tool (core or other plugin), loading fails with `ValueError`.

**Policy:** `SERIAL_MCP_PLUGINS` env var is parsed into `(enabled, allowlist)`. The `PluginManager` checks this before every `load()` call. `load_all()` skips entirely when disabled.

**Hot reload:** `reload(name)` calls `unload(name)` then `load(path)`. Unload filters the TOOLS list in-place and pops handler keys. The old module is deleted from `sys.modules`.

**Limitation:** MCP clients may not refresh their tool list mid-session. Newly loaded plugins may require a client restart to call their tools. Hot-reload of existing plugins works without restart.

## MCP Inspector

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) lets you call tools without an agent:

```bash
npx @modelcontextprotocol/inspector python -m serial_mcp_server
```

Open the URL with the auth token printed in the terminal. Use the **Tools** tab to call any tool interactively.

## Tests

All tests run without serial hardware. They use `MagicMock` for pyserial objects, `tmp_path` fixtures for filesystem isolation, and `monkeypatch` for environment variables.

```bash
# Run all tests
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_plugins.py -v

# Run a specific test
python -m pytest tests/test_plugins.py::TestPluginManager::test_load_adds_tools_and_handlers -v
```
