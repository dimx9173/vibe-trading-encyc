"""IC/IR 計算工具

實現信息係數（IC）和信息比率（IR）的計算。
"""
import pandas as pd
import numpy as np


def calculate_ic(
    factor_values: pd.Series,
    forward_returns: pd.Series,
    method: str = "spearman"
) -> float:
    """計算單期信息係數（IC）

    IC 衡量因子值與未來收益的相關性，是評估因子預測能力的核心指標。

    Args:
        factor_values: 因子值序列
        forward_returns: 未來收益序列（與 factor_values 對齊）
        method: 相關性方法
            - "spearman": 斯皮爾曼秩相關（預設，對異常值更穩健）
            - "pearson": 皮爾遜相關

    Returns:
        float: IC 值，範圍 [-1, 1]
            - |IC| > 0.03: 因子有預測能力
            - |IC| > 0.05: 因子預測能力較強
            - |IC| > 0.1: 因子預測能力很強

    Raises:
        ValueError: 如果輸入序列長度不一致或包含 NaN
    """
    if len(factor_values) != len(forward_returns):
        raise ValueError(
            f"因子值和未來收益長度不一致: {len(factor_values)} vs {len(forward_returns)}"
        )

    # 移除 NaN
    mask = ~(factor_values.isna() | forward_returns.isna())
    fv = factor_values[mask]
    fr = forward_returns[mask]

    if len(fv) < 2:
        return 0.0

    if method == "spearman":
        result = fv.corr(fr, method="spearman")
    elif method == "pearson":
        result = fv.corr(fr, method="pearson")
    else:
        raise ValueError(f"不支援的 method: {method}")
    
    return float(result)


def calculate_ic_series(
    factor_df: pd.DataFrame,
    returns_df: pd.DataFrame,
    method: str = "spearman"
) -> pd.Series:
    """計算時間序列的 IC

    對每個時間截面計算 IC，返回 IC 時間序列。

    Args:
        factor_df: 因子值 DataFrame，index 為日期，columns 為資產
        returns_df: 未來收益 DataFrame，結構同 factor_df
        method: 相關性方法（"spearman" 或 "pearson"）

    Returns:
        pd.Series: IC 時間序列，index 為日期
    """
    ic_values = []
    common_dates = factor_df.index.intersection(returns_df.index)

    for date in common_dates:
        fv = factor_df.loc[date].dropna()
        fr = returns_df.loc[date].dropna()

        # 只計算共同存在的資產
        common_assets = fv.index.intersection(fr.index)
        if len(common_assets) < 2:
            ic_values.append(np.nan)
            continue

        ic = calculate_ic(fv[common_assets], fr[common_assets], method)
        ic_values.append(ic)

    return pd.Series(ic_values, index=common_dates, name="IC")


def calculate_ir(
    ic_series: pd.Series,
    periods_per_year: int = 365
) -> float:
    """計算信息比率（IR）

    IR = IC_mean / IC_std * sqrt(periods_per_year)
    IR 衡量因子預測能力的穩定性。

    Args:
        ic_series: IC 時間序列
        periods_per_year: 年化因子
            - 日頻: 365（crypto）或 252（股票）
            - 小時頻: 8760（crypto）
            - 分鐘頻: 525600

    Returns:
        float: IR 值
            - |IR| > 0.5: 優秀因子
            - |IR| > 0.3: 良好因子
            - |IR| > 0.1: 可用因子

    Raises:
        ValueError: 如果 IC 序列標準差為 0
    """
    ic_clean = ic_series.dropna()

    if len(ic_clean) < 2:
        return 0.0

    ic_mean = float(ic_clean.mean())
    ic_std = float(ic_clean.std())

    if ic_std == 0:
        return 0.0

    # 年化 IR
    ir = (ic_mean / ic_std) * np.sqrt(periods_per_year)

    return ir


def calculate_ic_summary(
    factor_df: pd.DataFrame,
    returns_df: pd.DataFrame,
    method: str = "spearman",
    periods_per_year: int = 365
) -> dict[str, float]:
    """計算 IC/IR 摘要統計

    Args:
        factor_df: 因子值 DataFrame
        returns_df: 未來收益 DataFrame
        method: 相關性方法
        periods_per_year: 年化因子

    Returns:
        dict: 包含以下鍵值：
            - ic_mean: IC 均值
            - ic_std: IC 標準差
            - ir: 信息比率
            - icir: IC/IR（等同於 ir）
            - ic_positive_ratio: IC > 0 的比例
            - ic_abs_gt_002: |IC| > 0.02 的比例
            - ic_abs_gt_005: |IC| > 0.05 的比例
            - total_periods: 總期數
    """
    ic_series = calculate_ic_series(factor_df, returns_df, method)
    ic_clean = ic_series.dropna()

    if len(ic_clean) == 0:
        return {
            "ic_mean": 0.0,
            "ic_std": 0.0,
            "ir": 0.0,
            "icir": 0.0,
            "ic_positive_ratio": 0.0,
            "ic_abs_gt_002": 0.0,
            "ic_abs_gt_005": 0.0,
            "total_periods": 0,
        }

    ic_mean = float(ic_clean.mean())
    ic_std = float(ic_clean.std())
    ir = calculate_ir(ic_series, periods_per_year)

    return {
        "ic_mean": ic_mean,
        "ic_std": ic_std,
        "ir": ir,
        "icir": ir,
        "ic_positive_ratio": float((ic_clean > 0).mean()),
        "ic_abs_gt_002": float((ic_clean.abs() > 0.02).mean()),
        "ic_abs_gt_005": float((ic_clean.abs() > 0.05).mean()),
        "total_periods": len(ic_clean),
    }
