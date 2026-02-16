"""Unit tests for server-level helpers and build_server wiring."""

import json

from serial_mcp_server.helpers import _err, _ok, _result_text

# ---------------------------------------------------------------------------
# Result format tests
# ---------------------------------------------------------------------------


class TestResultFormat:
    def test_ok_shape(self):
        r = _ok(foo="bar")
        assert r == {"ok": True, "foo": "bar"}

    def test_err_shape(self):
        r = _err("some_code", "some message")
        assert r == {"ok": False, "error": {"code": "some_code", "message": "some message"}}

    def test_result_text_is_json(self):
        payload = {"ok": True, "x": 1}
        texts = _result_text(payload)
        assert len(texts) == 1
        parsed = json.loads(texts[0].text)
        assert parsed == payload


# ---------------------------------------------------------------------------
# build_server wiring
# ---------------------------------------------------------------------------


class TestBuildServer:
    def test_build_server_returns_server_and_state(self):
        from serial_mcp_server.server import build_server

        server, state = build_server()
        assert server is not None
        assert state is not None
        assert hasattr(state, "connections")
