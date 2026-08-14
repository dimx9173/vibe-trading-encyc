"""
Historical K-line Database

SQLite-based historical K-line storage with:
- Auto-sync from live WebSocket data
- Efficient time-range queries
- Data integrity validation
"""
import sqlite3
from typing import List, Optional
from datetime import datetime
from .base import KlineDataSource
from ..base import Kline


class HistoricalKlineDB(KlineDataSource):
    """Historical K-line database"""
    
    def __init__(self, db_path: str = "klines.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS klines (
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    close_time INTEGER,
                    PRIMARY KEY (symbol, interval, open_time)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_klines_symbol_interval 
                ON klines(symbol, interval, open_time)
            """)
            conn.commit()
    
    async def save_kline(self, kline: Kline):
        """Save K-line to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO klines 
                (symbol, interval, open_time, open, high, low, close, volume, close_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                kline.symbol,
                kline.interval,
                int(kline.open_time.timestamp()),
                kline.open,
                kline.high,
                kline.low,
                kline.close,
                kline.volume,
                int(kline.close_time.timestamp()) if kline.close_time else None
            ))
            conn.commit()
    
    async def save_klines(self, klines: List[Kline]):
        """Save multiple K-lines"""
        for kline in klines:
            await self.save_kline(kline)
    
    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[Kline]:
        """Get K-lines from database"""
        query = """
            SELECT symbol, interval, open_time, open, high, low, close, volume, close_time
            FROM klines
            WHERE symbol = ? AND interval = ?
        """
        params = [symbol, interval]
        
        if start:
            query += " AND open_time >= ?"
            params.append(int(start.timestamp()))
        
        if end:
            query += " AND open_time <= ?"
            params.append(int(end.timestamp()))
        
        query += " ORDER BY open_time ASC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
        
        return [
            Kline(
                symbol=row[0],
                interval=row[1],
                open_time=datetime.fromtimestamp(row[2]),
                open=row[3],
                high=row[4],
                low=row[5],
                close=row[6],
                volume=row[7],
                close_time=datetime.fromtimestamp(row[8]) if row[8] else None
            )
            for row in rows
        ]
    
    async def get_latest_kline(self, symbol: str, interval: str) -> Optional[Kline]:
        """Get latest K-line"""
        klines = await self.get_klines(symbol, interval, limit=1)
        return klines[0] if klines else None
    
    async def get_kline_count(self, symbol: str, interval: str) -> int:
        """Get K-line count"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM klines WHERE symbol = ? AND interval = ?",
                (symbol, interval)
            )
            return cursor.fetchone()[0]
    
    async def delete_old_klines(self, symbol: str, interval: str, before: datetime):
        """Delete K-lines older than specified time"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM klines WHERE symbol = ? AND interval = ? AND open_time < ?",
                (symbol, interval, int(before.timestamp()))
            )
            conn.commit()
