"""SQLite audit storage for risk checks and order submissions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import aiosqlite

from vibe_trading.config.settings import get_settings


class ExecutionAuditStorage:
    """Persist execution risk checks and order results."""

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or get_settings().database_url
        self.db_path = self._resolve_db_path(self.database_url)

    @staticmethod
    def _resolve_db_path(database_url: str) -> str:
        if database_url.startswith("sqlite+aiosqlite:///"):
            raw_path = database_url.replace("sqlite+aiosqlite:///", "", 1)
        elif database_url.startswith("sqlite:///"):
            raw_path = database_url.replace("sqlite:///", "", 1)
        else:
            raw_path = "vibe_trading.db"
        return str(Path(raw_path).expanduser())

    async def init(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_risk_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time_ms INTEGER,
                    verdict TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time_ms INTEGER,
                    order_id TEXT,
                    status TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time_ms INTEGER,
                    order_id TEXT NOT NULL,
                    fill_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    fee REAL,
                    fee_asset TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_position_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time_ms INTEGER,
                    positions_json TEXT NOT NULL,
                    balances_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_risk_trace ON execution_risk_checks(trace_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_orders_trace ON execution_orders(trace_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_fills_trace ON execution_fills(trace_id)")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_execution_position_snapshots_trace ON execution_position_snapshots(trace_id)"
            )
            await conn.commit()

    async def record_risk_check(
        self,
        *,
        trace_id: str,
        symbol: str,
        interval: str,
        open_time_ms: Optional[int],
        verdict: str,
        reason: str,
        request: Dict[str, Any],
        metrics: Dict[str, Any],
    ) -> None:
        await self.init()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO execution_risk_checks (
                    trace_id, symbol, interval, open_time_ms, verdict, reason,
                    request_json, metrics_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    symbol,
                    interval,
                    open_time_ms,
                    verdict,
                    reason,
                    json.dumps(request, ensure_ascii=False),
                    json.dumps(metrics, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            await conn.commit()

    async def record_order(
        self,
        *,
        trace_id: str,
        symbol: str,
        interval: str,
        open_time_ms: Optional[int],
        order_id: Optional[str],
        status: str,
        side: str,
        order_type: str,
        quantity: float,
        result: Dict[str, Any],
    ) -> None:
        await self.init()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO execution_orders (
                    trace_id, symbol, interval, open_time_ms, order_id, status,
                    side, order_type, quantity, result_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    symbol,
                    interval,
                    open_time_ms,
                    order_id,
                    status,
                    side,
                    order_type,
                    quantity,
                    json.dumps(result, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            await conn.commit()

    async def get_trace(self, trace_id: str) -> Dict[str, list[Dict[str, Any]]]:
        await self.init()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            risk_cursor = await conn.execute(
                "SELECT * FROM execution_risk_checks WHERE trace_id = ? ORDER BY id",
                (trace_id,),
            )
            order_cursor = await conn.execute(
                "SELECT * FROM execution_orders WHERE trace_id = ? ORDER BY id",
                (trace_id,),
            )
            fill_cursor = await conn.execute(
                "SELECT * FROM execution_fills WHERE trace_id = ? ORDER BY id",
                (trace_id,),
            )
            snapshot_cursor = await conn.execute(
                "SELECT * FROM execution_position_snapshots WHERE trace_id = ? ORDER BY id",
                (trace_id,),
            )
            risk_rows = await risk_cursor.fetchall()
            order_rows = await order_cursor.fetchall()
            fill_rows = await fill_cursor.fetchall()
            snapshot_rows = await snapshot_cursor.fetchall()

        return {
            "risk_checks": [self._risk_row_to_dict(row) for row in risk_rows],
            "orders": [self._order_row_to_dict(row) for row in order_rows],
            "fills": [dict(row) for row in fill_rows],
            "position_snapshots": [self._snapshot_row_to_dict(row) for row in snapshot_rows],
        }

    async def record_fill(
        self,
        *,
        trace_id: str,
        symbol: str,
        interval: str,
        open_time_ms: Optional[int],
        order_id: str,
        fill_id: str,
        side: str,
        quantity: float,
        price: float,
        fee: Optional[float],
        fee_asset: Optional[str],
    ) -> None:
        await self.init()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO execution_fills (
                    trace_id, symbol, interval, open_time_ms, order_id, fill_id,
                    side, quantity, price, fee, fee_asset, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    symbol,
                    interval,
                    open_time_ms,
                    order_id,
                    fill_id,
                    side,
                    quantity,
                    price,
                    fee,
                    fee_asset,
                    datetime.now().isoformat(),
                ),
            )
            await conn.commit()

    async def record_position_snapshot(
        self,
        *,
        trace_id: str,
        symbol: str,
        interval: str,
        open_time_ms: Optional[int],
        positions: list[Dict[str, Any]],
        balances: Dict[str, Any],
    ) -> None:
        await self.init()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO execution_position_snapshots (
                    trace_id, symbol, interval, open_time_ms,
                    positions_json, balances_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    symbol,
                    interval,
                    open_time_ms,
                    json.dumps(positions, ensure_ascii=False),
                    json.dumps(balances, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            await conn.commit()

    def _risk_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        data = dict(row)
        data["request"] = json.loads(data.pop("request_json"))
        data["metrics"] = json.loads(data.pop("metrics_json"))
        return data

    def _order_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        data = dict(row)
        data["result"] = json.loads(data.pop("result_json"))
        return data

    def _snapshot_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        data = dict(row)
        data["positions"] = json.loads(data.pop("positions_json"))
        data["balances"] = json.loads(data.pop("balances_json"))
        return data
