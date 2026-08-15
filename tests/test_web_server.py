"""Tests for web/server routes (Wave D — coverage 85% plan).

FastAPI TestClient. journal_storage 用 :memory: — 避免真實 DB.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from unittest.mock import AsyncMock as _AsyncMock

import pytest
from fastapi.testclient import TestClient

import vibe_trading.web.server as web_server
from vibe_trading.web.server import app, set_initial_config, state


@pytest.fixture
def client():
    # 避免 startup_event 初始化真實 journal DB
    with patch.object(web_server.journal_storage, "init", new=AsyncMock()):
        with TestClient(app) as c:
            yield c


class TestStatus:
    def test_get_status(self, client):
        with patch.object(web_server.journal_storage, "count_bars",
                          new=AsyncMock(return_value=5)):
            r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert "connected_clients" in data
        assert data["total_decisions"] == 5

    def test_get_status_db_error_fallback(self, client):
        with patch.object(web_server.journal_storage, "count_bars",
                          new=AsyncMock(side_effect=RuntimeError("no table"))):
            r = client.get("/api/status")
        assert r.status_code == 200
        assert r.json()["total_decisions"] == 0


class TestKlines:
    def test_get_klines_empty(self, client):
        state.klines = []
        r = client.get("/api/klines")
        assert r.status_code == 200
        assert r.json() == {"klines": []}

    def test_get_klines_with_data(self, client):
        state.klines = [{"close": 50000.0}]
        r = client.get("/api/klines")
        assert r.json() == {"klines": [{"close": 50000.0}]}


class TestDecisions:
    def test_get_decisions_empty(self, client):
        with patch.object(web_server.journal_storage, "list_bars",
                          new=AsyncMock(return_value=[])):
            r = client.get("/api/decisions")
        assert r.status_code == 200
        assert r.json() == {"decisions": []}

    def test_get_decisions_with_data(self, client):
        bar = MagicMock()
        bar.decision = {"action": "BUY", "confidence": 0.9}
        with patch.object(web_server.journal_storage, "list_bars",
                          new=AsyncMock(return_value=[bar])):
            r = client.get("/api/decisions")
        assert r.json() == {"decisions": [{"action": "BUY", "confidence": 0.9}]}

    def test_get_decisions_db_error(self, client):
        with patch.object(web_server.journal_storage, "list_bars",
                          new=AsyncMock(side_effect=RuntimeError("no table"))):
            r = client.get("/api/decisions")
        assert r.status_code == 200
        assert r.json() == {"decisions": []}


class TestInitConfig:
    def test_post_init(self, client):
        r = client.post("/api/init", json={"symbol": "ETHUSDT", "interval": "1h"})
        assert r.status_code == 200
        assert state.current_symbol == "ETHUSDT"


class TestConnectionState:
    def test_broadcast_sends_text(self):
        cs = web_server.ConnectionState()
        ws = _AsyncMock()
        cs.active_connections.append(ws)
        asyncio_run(cs.broadcast({"type": "x"}))
        ws.send_text.assert_called_once()
        import json as _json
        payload = _json.loads(ws.send_text.call_args[0][0])
        assert payload["type"] == "x"

    def test_broadcast_no_connections(self):
        cs = web_server.ConnectionState()
        asyncio_run(cs.broadcast({"type": "x"}))  # 不 raise

    def test_broadcast_errors_swallowed(self):
        cs = web_server.ConnectionState()
        ws1, ws2 = _AsyncMock(), _AsyncMock()
        ws1.send_text.side_effect = RuntimeError("disconnected")
        cs.active_connections.extend([ws1, ws2])
        asyncio_run(cs.broadcast({"type": "x"}))  # return_exceptions=True 吞錯
        assert len(cs.active_connections) == 2  # 不主動移除

    def test_send_update(self):
        cs = web_server.ConnectionState()
        ws = _AsyncMock()
        cs.active_connections.append(ws)
        asyncio_run(cs.send_update("event", {"k": 1}))
        ws.send_text.assert_called_once()


def asyncio_run(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
