"""Alpha 基類定義

定義所有因子的基礎結構和元數據規範。
"""
from dataclasses import dataclass, field
from typing import Protocol, List, Dict, Any, Optional, runtime_checkable
from datetime import datetime
import pandas as pd


@dataclass
class AlphaMetadata:
    """因子元數據

    Attributes:
        name: 因子名稱（唯一識別符）
        formula: LaTeX 公式描述
        universe: 適用的市場/資產類型（如 "crypto_perp", "spot"）
        column_dependencies: 依賴的 OHLCV 欄位列表
        warmup_periods: 需要的預熱期數
        version: 版本號
        author: 作者
        created_at: 創建時間
        description: 因子描述
        tags: 標籤列表（如 ["momentum", "trend"]）
    """
    name: str
    formula: str
    universe: str
    column_dependencies: List[str]
    warmup_periods: int
    version: str = "1.0.0"
    author: str = "unknown"
    created_at: datetime = field(default_factory=datetime.now)
    description: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典格式"""
        return {
            "name": self.name,
            "formula": self.formula,
            "universe": self.universe,
            "column_dependencies": self.column_dependencies,
            "warmup_periods": self.warmup_periods,
            "version": self.version,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "description": self.description,
            "tags": self.tags,
        }


@runtime_checkable
class Alpha(Protocol):
    """因子協議

    所有因子必須實現此協議，提供：
    1. __alpha_meta__: 因子元數據
    2. compute(): 計算因子值的方法
    """

    __alpha_meta__: AlphaMetadata

    def compute(self, data: pd.DataFrame) -> pd.Series:
        """計算因子值

        Args:
            data: OHLCV DataFrame，必須包含 __alpha_meta__.column_dependencies 中的所有欄位

        Returns:
            pd.Series: 因子值序列，index 與輸入 data 相同

        Raises:
            ValueError: 如果數據不足或缺少必要欄位
        """
        ...


def validate_alpha_columns(alpha: Alpha, data: pd.DataFrame) -> None:
    """驗證數據是否包含因子所需的所有欄位

    Args:
        alpha: 因子實例
        data: OHLCV DataFrame

    Raises:
        ValueError: 如果缺少必要欄位
    """
    missing = set(alpha.__alpha_meta__.column_dependencies) - set(data.columns)
    if missing:
        raise ValueError(
            f"因子 {alpha.__alpha_meta__.name} 缺少必要欄位: {sorted(missing)}"
        )


def validate_warmup(alpha: Alpha, data: pd.DataFrame) -> None:
    """驗證數據是否滿足預熱期要求

    Args:
        alpha: 因子實例
        data: OHLCV DataFrame

    Raises:
        ValueError: 如果數據不足
    """
    required = alpha.__alpha_meta__.warmup_periods
    actual = len(data)
    if actual < required:
        raise ValueError(
            f"因子 {alpha.__alpha_meta__.name} 需要 {required} 期數據，"
            f"但只有 {actual} 期"
        )
