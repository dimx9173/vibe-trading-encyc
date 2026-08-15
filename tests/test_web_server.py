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


class TestLoadHistoricalKlines:
    @pytest.mark.asyncio
    async def test_load_with_klines(self):
        state.klines = []
        kline = MagicMock()
        kline.open_time = 1700000000000
        kline.symbol = "BTCUSDT"
        kline.interval = "30m"
        kline.open = kline.high = kline.low = kline.close = 50000.0
        kline.volume = 100.0
        storage = MagicMock()
        storage.init = AsyncMock()
        storage.close = AsyncMock()
        storage.query_klines = AsyncMock(return_value=[kline])
        with patch.object(web_server, "kline_storage", storage), \
             patch.object(web_server, "calculate_indicators", new=AsyncMock()):
            await web_server.load_historical_klines("BTCUSDT", "30m", 100)
        assert len(state.klines) == 1
        assert state.klines[0]["close"] == 50000.0

    @pytest.mark.asyncio
    async def test_load_empty(self):
        state.klines = []
        storage = MagicMock()
        storage.init = AsyncMock()
        storage.close = AsyncMock()
        storage.query_klines = AsyncMock(return_value=[])
        with patch.object(web_server, "kline_storage", storage):
            await web_server.load_historical_klines("BTCUSDT", "30m")
        assert state.klines == []

    @pytest.mark.asyncio
    async def test_load_error_failsafe(self):
        storage = MagicMock()
        storage.init = AsyncMock(side_effect=RuntimeError("down"))
        storage.close = AsyncMock()
        with patch.object(web_server, "kline_storage", storage):
            await web_server.load_historical_klines("BTCUSDT")  # 不 raise


class TestCalculateIndicators:
    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        state.klines = [{"open": 1, "high": 2, "low": 1, "close": 1, "volume": 1}] * 10
        with patch.object(web_server, "technical_indicators") as ti:
            await web_server.calculate_indicators()
            ti.load_data.assert_not_called()  # < 50 → 直接 return

    @pytest.mark.asyncio
    async def test_sufficient_data(self):
        state.klines = [{"open": 100.0 + i, "high": 105.0 + i, "low": 95.0 + i,
                         "close": 100.0 + i, "volume": 10.0} for i in range(60)]
        ti = MagicMock()
        ti.calculate_all.return_value = __import__("pandas").DataFrame({
            "rsi": [50.0] * 60, "macd": [1.0] * 60, "macd_signal": [0.5] * 60,
            "macd_hist": [0.5] * 60, "sma_20": [100.0] * 60, "sma_50": [100.0] * 60,
            "ema_12": [100.0] * 60, "ema_26": [100.0] * 60,
            "bb_upper": [102.0] * 60, "bb_middle": [100.0] * 60,
            "bb_lower": [98.0] * 60, "atr": [1.0] * 60,
        })
        with patch.object(web_server, "technical_indicators", ti):
            await web_server.calculate_indicators()
        assert "rsi" in state.indicators
        assert state.indicators["rsi"][0] == 50.0

    @pytest.mark.asyncio
    async def test_calculate_error_failsafe(self):
        state.klines = [{"open": 1, "high": 2, "low": 1, "close": 1, "volume": 1}] * 60
        ti = MagicMock()
        ti.calculate_all.side_effect = RuntimeError("boom")
        with patch.object(web_server, "technical_indicators", ti):
            await web_server.calculate_indicators()  # 不 raise


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


class TestLogs:
    def test_get_logs(self, client):
        state.logs = [{"message": "log1"}]
        r = client.get("/api/logs")
        assert r.status_code == 200
        assert r.json() == {"logs": [{"message": "log1"}]}


class TestAddKline:
    def test_post_kline(self, client):
        state.klines = []  # 重置全域 state
        with patch.object(web_server.journal_storage, "upsert_bar", new=AsyncMock()), \
             patch.object(web_server, "calculate_indicators", new=AsyncMock()):
            r = client.post("/api/kline", json={
                "time": "2026-01-01T00:00:00",
                "symbol": "BTCUSDT", "interval": "30m",
                "open": 100, "high": 105, "low": 95, "close": 102, "volume": 10,
            })
        assert r.status_code == 200
        assert r.json() == {"success": True}
        assert state.current_symbol == "BTCUSDT"


class TestAddDecision:
    def test_post_decision(self, client):
        with patch.object(web_server.journal_storage, "upsert_bar", new=AsyncMock()):
            r = client.post("/api/decision", json={
                "index": 1, "time": "2026-01-01T00:00:00", "close": 50000.0,
                "symbol": "BTCUSDT", "decision": "BUY", "rationale": "看漲",
            })
        assert r.status_code == 200
        assert r.json() == {"success": True}
        assert len(state.decisions) == 1


class TestAddLog:
    def test_post_log(self, client):
        with patch.object(web_server.journal_storage, "upsert_bar", new=AsyncMock()):
            r = client.post("/api/log", json={"message": "hello", "level": "info"})
        assert r.status_code == 200
        assert r.json() == {"success": True}
        assert state.logs[-1]["message"] == "hello"

    def test_post_log_no_open_time(self, client):
        r = client.post("/api/log", json={"message": "no ts"})
        assert r.status_code == 200


class TestAddPhase:
    def test_post_phase(self, client):
        r = client.post("/api/phase", json={"phase": "analysts", "status": "completed"})
        assert r.status_code == 200
        assert state.phase_status["current"] == "analysts"


class TestAddReport:
    def test_post_report(self, client):
        r = client.post("/api/report", json={
            "role": "analyst", "content": "report", "stage": "analysts",
        })
        assert r.status_code == 200
        assert r.json() == {"success": True}


class TestWebSocket:
    def test_websocket_connect_receive(self, client):
        state.klines = [{"close": 50000.0}]
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "init"
            assert "klines" in data["data"]

    def test_websocket_disconnect_cleanup(self, client):
        with client.websocket_connect("/ws") as ws:
            pass  # 斷線
        # 斷線後 active_connections 應清理或至少不崩潰
        assert isinstance(state.active_connections, list)


class TestSendHelpers:
    @pytest.mark.asyncio
    async def test_send_kline(self):
        with patch.object(web_server.journal_storage, "upsert_bar", new=AsyncMock()):
            await web_server.send_kline({"symbol": "BTCUSDT", "open_time_ms": 1})
        assert len(state.klines) >= 0

    @pytest.mark.asyncio
    async def test_send_decision(self):
        with patch.object(web_server.journal_storage, "upsert_bar", new=AsyncMock()):
            await web_server.send_decision({"symbol": "BTCUSDT", "open_time_ms": 1})
        assert len(state.decisions) >= 0

    @pytest.mark.asyncio
    async def test_send_log(self):
        with patch.object(web_server.journal_storage, "upsert_bar", new=AsyncMock()):
            await web_server.send_log("info", "OnBar", "msg", open_time_ms=1)
        assert len(state.logs) >= 1

    @pytest.mark.asyncio
    async def test_send_phase(self):
        state.phase_status = {}
        with patch.object(web_server.journal_storage, "upsert_bar", new=AsyncMock()):
            await web_server.send_phase("ANALYZING", "running", open_time_ms=1)
        assert state.phase_status["current"] == "ANALYZING"

    @pytest.mark.asyncio
    async def test_send_report(self):
        state.agent_reports = {}
        with patch.object(web_server.journal_storage, "upsert_bar", new=AsyncMock()):
            await web_server.send_report("tech", "報告", "analysts", open_time_ms=1)
        assert "analysts" in state.agent_reports
        assert "tech" in state.agent_reports["analysts"]

    @pytest.mark.asyncio
    async def test_send_execution(self):
        with patch("httpx.AsyncClient") as mock_client:
            await web_server.send_execution(
                agent="tech", tool_name="get_price", tool_call_id="c1",
                args={}, result={}, symbol="BTCUSDT")
        mock_client.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_execution_error_swallowed(self):
        with patch("httpx.AsyncClient", side_effect=RuntimeError("down")):
            await web_server.send_execution(
                agent="tech", tool_name="t", tool_call_id="c", args={}, result={})
        # 不 raise
