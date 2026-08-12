"""Binance CSV 交易記錄解析器"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .models import TradeRecord


def parse_binance_csv(csv_path: str | Path) -> List[TradeRecord]:
    """解析 Binance 交易歷史 CSV

    Args:
        csv_path: CSV 文件路徑

    Returns:
        TradeRecord 列表

    CSV 格式（Binance Futures）:
        UTC_Time, Account, Pair, Side, Action, Price, Quantity, Fee, Fee_Currency, Realized_Profit, Trade_ID
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV 文件不存在: {csv_path}")

    trades: List[TradeRecord] = []

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                entry_time = datetime.fromisoformat(row["UTC_Time"].replace("Z", "+00:00"))
                side = row["Side"].upper()
                action = row["Action"].upper()

                # Binance CSV 每筆是單邊，需要配對成完整交易
                trade = TradeRecord(
                    trade_id=row.get("Trade_ID", ""),
                    symbol=row["Pair"].replace("/", ""),
                    side=side,
                    entry_time=entry_time,
                    entry_price=float(row["Price"]),
                    quantity=float(row["Quantity"]),
                    fee=float(row.get("Fee", 0)),
                    pnl=float(row.get("Realized_Profit", 0)),
                    is_closed=(action == "CLOSE"),
                    metadata={
                        "action": action,
                        "fee_currency": row.get("Fee_Currency", ""),
                    },
                )
                trades.append(trade)

            except (KeyError, ValueError) as e:
                # 跳過無效行
                continue

    return trades


def pair_trades(trades: List[TradeRecord]) -> List[TradeRecord]:
    """將單邊交易配對成完整交易

    Args:
        trades: 單邊交易列表（按時間排序）

    Returns:
        配對後的完整交易列表
    """
    # 按 symbol 分組
    by_symbol: dict[str, List[TradeRecord]] = {}
    for t in trades:
        by_symbol.setdefault(t.symbol, []).append(t)

    paired: List[TradeRecord] = []

    for symbol, symbol_trades in by_symbol.items():
        # 按時間排序
        symbol_trades.sort(key=lambda t: t.entry_time)

        open_position: Optional[TradeRecord] = None

        for trade in symbol_trades:
            if trade.metadata.get("action") == "OPEN":
                open_position = trade
            elif trade.metadata.get("action") == "CLOSE" and open_position:
                # 配對
                open_position.exit_time = trade.entry_time
                open_position.exit_price = trade.entry_price
                open_position.pnl += trade.pnl
                open_position.fee += trade.fee
                open_position.is_closed = True
                paired.append(open_position)
                open_position = None
            elif trade.metadata.get("action") == "CLOSE":
                # 沒有對應的 OPEN，單獨記錄
                paired.append(trade)

        # 未平倉
        if open_position:
            paired.append(open_position)

    return paired
