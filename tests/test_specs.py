"""Tests for serial_mcp_server.specs — no serial hardware required."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from serial_mcp_server.specs import (
    compute_spec_id,
    get_template,
    list_specs,
    parse_frontmatter,
    read_spec,
    register_spec,
    resolve_spec_root,
    search_spec,
    validate_spec_meta,
)
from serial_mcp_server.state import SerialConnection, SerialState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_SPEC = """\
---
kind: serial-protocol
name: "Test Device"
---

# Test Device Protocol

## Overview

A test device spec.

## Commands

### Read Sensor

- **Write to**: `1234`
- **Format**: `[0x01]`
"""

MINIMAL_SPEC = """\
---
kind: serial-protocol
name: "Minimal"
---

# Minimal Spec
"""


def _write_spec(tmp_path: Path, content: str, name: str = "test-device.md") -> Path:
    """Write a spec file and return its path."""
    spec_dir = tmp_path / ".serial_mcp" / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_file = spec_dir / name
    spec_file.write_text(content, encoding="utf-8")
    return spec_file


def _setup_env(monkeypatch, tmp_path: Path) -> Path:
    """Set SERIAL_MCP_SPEC_ROOT to tmp_path/.serial_mcp and return it."""
    spec_root = tmp_path / ".serial_mcp"
    monkeypatch.setenv("SERIAL_MCP_SPEC_ROOT", str(spec_root))
    return spec_root


# ---------------------------------------------------------------------------
# Directory resolution
# ---------------------------------------------------------------------------


class TestResolveSpecRoot:
    def test_env_var(self, monkeypatch, tmp_path):
        target = tmp_path / "custom_specs"
        monkeypatch.setenv("SERIAL_MCP_SPEC_ROOT", str(target))
        assert resolve_spec_root() == target

    def test_walk_up_serial_mcp(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SERIAL_MCP_SPEC_ROOT", raising=False)
        # Create .serial_mcp in a parent
        serial_mcp_dir = tmp_path / ".serial_mcp"
        serial_mcp_dir.mkdir()
        child = tmp_path / "a" / "b"
        child.mkdir(parents=True)
        monkeypatch.chdir(child)
        assert resolve_spec_root() == serial_mcp_dir

    def test_walk_up_git(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SERIAL_MCP_SPEC_ROOT", raising=False)
        # Create .git in a parent
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        child = tmp_path / "sub"
        child.mkdir()
        monkeypatch.chdir(child)
        result = resolve_spec_root()
        assert result == tmp_path / ".serial_mcp"

    def test_cwd_fallback(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SERIAL_MCP_SPEC_ROOT", raising=False)
        monkeypatch.chdir(tmp_path)
        result = resolve_spec_root()
        assert result == tmp_path / ".serial_mcp"


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_valid(self):
        meta, body = parse_frontmatter(VALID_SPEC)
        assert meta["kind"] == "serial-protocol"
        assert meta["name"] == "Test Device"
        assert "# Test Device Protocol" in body

    def test_missing(self):
        content = "# No frontmatter here\n\nJust markdown."
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_invalid_yaml(self):
        content = "---\n[invalid yaml:: {\n---\nBody\n"
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_non_dict_yaml(self):
        content = "---\n- just\n- a\n- list\n---\nBody\n"
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidateSpecMeta:
    def test_valid(self):
        assert validate_spec_meta({"kind": "serial-protocol", "name": "Foo"}) == []

    def test_missing_kind(self):
        errors = validate_spec_meta({"name": "Foo"})
        assert len(errors) == 1
        assert "kind" in errors[0]

    def test_wrong_kind(self):
        errors = validate_spec_meta({"kind": "other", "name": "Foo"})
        assert len(errors) == 1

    def test_missing_name(self):
        errors = validate_spec_meta({"kind": "serial-protocol"})
        assert len(errors) == 1
        assert "name" in errors[0]

    def test_empty_name(self):
        errors = validate_spec_meta({"kind": "serial-protocol", "name": ""})
        assert len(errors) == 1

    def test_multiple_errors(self):
        errors = validate_spec_meta({})
        assert len(errors) == 2


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegisterSpec:
    def test_valid(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        spec_file = _write_spec(tmp_path, VALID_SPEC)
        result = register_spec(spec_file)
        assert result["name"] == "Test Device"
        assert result["spec_id"]

    def test_missing_file(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        with pytest.raises(FileNotFoundError):
            register_spec(tmp_path / "nonexistent.md")

    def test_invalid_frontmatter(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        bad_spec = "---\nkind: wrong\n---\n# Bad\n"
        spec_file = _write_spec(tmp_path, bad_spec)
        with pytest.raises(ValueError, match="Invalid spec front-matter"):
            register_spec(spec_file)

    def test_idempotent(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        spec_file = _write_spec(tmp_path, VALID_SPEC)
        r1 = register_spec(spec_file)
        r2 = register_spec(spec_file)
        assert r1["spec_id"] == r2["spec_id"]

    def test_rejects_path_outside_project(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        outside = tmp_path.parent / "outside.md"
        outside.write_text(VALID_SPEC, encoding="utf-8")
        with pytest.raises(ValueError, match="must be inside the project"):
            register_spec(outside)

    def test_rejects_traversal_path(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        outside = tmp_path.parent / "sneaky.md"
        outside.write_text(VALID_SPEC, encoding="utf-8")
        traversal = tmp_path / ".serial_mcp" / "specs" / ".." / ".." / ".." / "sneaky.md"
        with pytest.raises(ValueError, match="must be inside the project"):
            register_spec(traversal)

    def test_allows_path_inside_project(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        # Spec in a subdirectory of the project (not in .serial_mcp/specs/)
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        spec_file = docs_dir / "my-device.md"
        spec_file.write_text(VALID_SPEC, encoding="utf-8")
        result = register_spec(spec_file)
        assert result["name"] == "Test Device"


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class TestListSpecs:
    def test_empty(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        assert list_specs() == []

    def test_lists_registered(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        spec_file = _write_spec(tmp_path, VALID_SPEC)
        entry = register_spec(spec_file)

        result = list_specs()
        assert len(result) == 1
        assert result[0]["spec_id"] == entry["spec_id"]
        assert result[0]["name"] == "Test Device"

    def test_multiple(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        _write_spec(tmp_path, VALID_SPEC, name="a.md")
        _write_spec(tmp_path, MINIMAL_SPEC, name="b.md")
        register_spec(tmp_path / ".serial_mcp" / "specs" / "a.md")
        register_spec(tmp_path / ".serial_mcp" / "specs" / "b.md")

        result = list_specs()
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Read spec
# ---------------------------------------------------------------------------


class TestReadSpec:
    def test_read(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        spec_file = _write_spec(tmp_path, VALID_SPEC)
        entry = register_spec(spec_file)

        result = read_spec(entry["spec_id"])
        assert result["spec_id"] == entry["spec_id"]
        assert result["meta"]["name"] == "Test Device"
        assert "# Test Device Protocol" in result["body"]
        assert result["content"] == VALID_SPEC

    def test_unknown_id(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        with pytest.raises(KeyError):
            read_spec("nonexistent0000")

    def test_rejects_path_outside_project_in_index(self, monkeypatch, tmp_path):
        """If index.json is tampered to point outside the project, read_spec refuses."""
        import json

        spec_root = _setup_env(monkeypatch, tmp_path)
        spec_root.mkdir(parents=True, exist_ok=True)
        # Write a tampered index pointing to a file outside the project
        index_path = spec_root / "index.json"
        index_path.write_text(
            json.dumps(
                {"bad": {"spec_id": "bad", "path": "/etc/passwd", "name": "Evil", "kind": "serial-protocol"}}
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="outside the project"):
            read_spec("bad")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearchSpec:
    def test_basic(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        spec_file = _write_spec(tmp_path, VALID_SPEC)
        entry = register_spec(spec_file)

        results = search_spec(entry["spec_id"], "sensor")
        assert len(results) > 0
        assert results[0]["line"] > 0
        assert "sensor" in results[0]["text"].lower()

    def test_line_numbers(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        spec_file = _write_spec(tmp_path, VALID_SPEC)
        entry = register_spec(spec_file)

        results = search_spec(entry["spec_id"], "Commands")
        assert len(results) > 0
        for r in results:
            assert isinstance(r["line"], int)
            assert r["line"] > 0

    def test_k_limit(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        spec_file = _write_spec(tmp_path, VALID_SPEC)
        entry = register_spec(spec_file)

        results = search_spec(entry["spec_id"], "a", k=2)
        assert len(results) <= 2

    def test_context(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        spec_file = _write_spec(tmp_path, VALID_SPEC)
        entry = register_spec(spec_file)

        results = search_spec(entry["spec_id"], "sensor")
        assert len(results) > 0
        assert "context" in results[0]
        # Context should contain line numbers
        assert ":" in results[0]["context"]


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


class TestGetTemplate:
    def test_default(self):
        template = get_template()
        assert "kind: serial-protocol" in template
        assert "My Device" in template

    def test_with_device_name(self):
        template = get_template("SensorTag")
        assert "SensorTag" in template
        assert 'name: "SensorTag Protocol"' in template


# ---------------------------------------------------------------------------
# Spec ID
# ---------------------------------------------------------------------------


class TestComputeSpecId:
    def test_deterministic(self, tmp_path):
        p = tmp_path / "test.md"
        p.touch()
        id1 = compute_spec_id(p)
        id2 = compute_spec_id(p)
        assert id1 == id2
        assert len(id1) == 16

    def test_different_paths(self, tmp_path):
        p1 = tmp_path / "a.md"
        p2 = tmp_path / "b.md"
        p1.touch()
        p2.touch()
        assert compute_spec_id(p1) != compute_spec_id(p2)


# ---------------------------------------------------------------------------
# Spec handler tests
# ---------------------------------------------------------------------------


class TestSpecHandlers:
    """Tests for handler functions in serial_mcp_server.handlers_spec."""

    async def test_template_returns_template_and_path(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_template

        state = SerialState()
        result = await handle_spec_template(state, {})
        assert result["ok"] is True
        assert "kind: serial-protocol" in result["template"]
        assert "suggested_path" in result

    async def test_template_with_device_name(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_template

        state = SerialState()
        result = await handle_spec_template(state, {"device_name": "SensorTag"})
        assert result["ok"] is True
        assert "SensorTag" in result["template"]
        assert "sensortag" in result["suggested_path"]

    async def test_register_success(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_register

        spec_file = _write_spec(tmp_path, VALID_SPEC)
        state = SerialState()
        result = await handle_spec_register(state, {"path": str(spec_file)})
        assert result["ok"] is True
        assert result["name"] == "Test Device"
        assert result["spec_id"]

    async def test_register_file_not_found(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_register

        state = SerialState()
        result = await handle_spec_register(state, {"path": str(tmp_path / "nope.md")})
        assert result["ok"] is False
        assert result["error"]["code"] == "not_found"

    async def test_register_invalid_frontmatter(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_register

        bad_spec = "---\nkind: wrong\n---\n# Bad\n"
        spec_file = _write_spec(tmp_path, bad_spec)
        state = SerialState()
        result = await handle_spec_register(state, {"path": str(spec_file)})
        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_spec"

    async def test_list_empty(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_list

        state = SerialState()
        result = await handle_spec_list(state, {})
        assert result["ok"] is True
        assert result["count"] == 0
        assert result["specs"] == []

    async def test_list_with_registered(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_list

        spec_file = _write_spec(tmp_path, VALID_SPEC)
        register_spec(spec_file)

        state = SerialState()
        result = await handle_spec_list(state, {})
        assert result["ok"] is True
        assert result["count"] == 1

    async def test_attach_success(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_attach

        spec_file = _write_spec(tmp_path, VALID_SPEC)
        entry_data = register_spec(spec_file)

        state = SerialState()
        conn = SerialConnection(
            connection_id="c1",
            port="/dev/ttyUSB0",
            baudrate=115200,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=0.2,
            write_timeout=0.2,
            encoding="utf-8",
            newline="\n",
            ser=MagicMock(),
        )
        state.connections["c1"] = conn

        result = await handle_spec_attach(
            state,
            {
                "connection_id": "c1",
                "spec_id": entry_data["spec_id"],
            },
        )
        assert result["ok"] is True
        assert result["spec_id"] == entry_data["spec_id"]
        assert conn.spec is not None
        assert conn.spec["spec_id"] == entry_data["spec_id"]

    async def test_attach_unknown_spec_id(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_attach

        state = SerialState()
        conn = SerialConnection(
            connection_id="c1",
            port="/dev/ttyUSB0",
            baudrate=115200,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=0.2,
            write_timeout=0.2,
            encoding="utf-8",
            newline="\n",
            ser=MagicMock(),
        )
        state.connections["c1"] = conn

        result = await handle_spec_attach(
            state,
            {
                "connection_id": "c1",
                "spec_id": "nonexistent",
            },
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "not_found"

    async def test_attach_unknown_connection_id(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_attach

        state = SerialState()
        with pytest.raises(KeyError, match="Unknown connection_id"):
            await handle_spec_attach(
                state,
                {
                    "connection_id": "nope",
                    "spec_id": "anything",
                },
            )

    async def test_get_returns_attached_spec(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_get

        state = SerialState()
        conn = SerialConnection(
            connection_id="c1",
            port="/dev/ttyUSB0",
            baudrate=115200,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=0.2,
            write_timeout=0.2,
            encoding="utf-8",
            newline="\n",
            ser=MagicMock(),
        )
        conn.spec = {"spec_id": "test123", "path": "/tmp/test.md", "meta": {}}
        state.connections["c1"] = conn

        result = await handle_spec_get(state, {"connection_id": "c1"})
        assert result["ok"] is True
        assert result["spec"]["spec_id"] == "test123"

    async def test_get_returns_none_when_no_spec(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_get

        state = SerialState()
        conn = SerialConnection(
            connection_id="c1",
            port="/dev/ttyUSB0",
            baudrate=115200,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=0.2,
            write_timeout=0.2,
            encoding="utf-8",
            newline="\n",
            ser=MagicMock(),
        )
        state.connections["c1"] = conn

        result = await handle_spec_get(state, {"connection_id": "c1"})
        assert result["ok"] is True
        assert result["spec"] is None

    async def test_read_success(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_read

        spec_file = _write_spec(tmp_path, VALID_SPEC)
        entry_data = register_spec(spec_file)

        state = SerialState()
        result = await handle_spec_read(state, {"spec_id": entry_data["spec_id"]})
        assert result["ok"] is True
        assert result["spec_id"] == entry_data["spec_id"]
        assert "# Test Device Protocol" in result["content"]

    async def test_read_unknown_spec_id(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_read

        state = SerialState()
        result = await handle_spec_read(state, {"spec_id": "nonexistent"})
        assert result["ok"] is False
        assert result["error"]["code"] == "not_found"

    async def test_search_returns_matches(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_search

        spec_file = _write_spec(tmp_path, VALID_SPEC)
        entry_data = register_spec(spec_file)

        state = SerialState()
        result = await handle_spec_search(
            state,
            {
                "spec_id": entry_data["spec_id"],
                "query": "sensor",
            },
        )
        assert result["ok"] is True
        assert result["count"] > 0
        assert len(result["results"]) > 0

    async def test_search_no_matches(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        from serial_mcp_server.handlers_spec import handle_spec_search

        spec_file = _write_spec(tmp_path, VALID_SPEC)
        entry_data = register_spec(spec_file)

        state = SerialState()
        result = await handle_spec_search(
            state,
            {
                "spec_id": entry_data["spec_id"],
                "query": "zzzznonexistent",
            },
        )
        assert result["ok"] is True
        assert result["count"] == 0
