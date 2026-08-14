"""Alpha 因子单元测试

测试所有因子的基本功能和正确性。
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from vibe_trading.backtest.alphas import (
    get_all_alphas,
    get_alphas_by_category,
    AlphaMetadata,
)
from vibe_trading.backtest.alphas.lookahead_guard import check_lookahead_bias
from vibe_trading.backtest.alphas.purity_gate import check_purity


def generate_test_data(periods: int = 100) -> pd.DataFrame:
    """生成测试用的 OHLCV 数据
    
    Args:
        periods: 数据期数
        
    Returns:
        OHLCV DataFrame
    """
    dates = [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(periods)]
    
    # 生成随机但合理的价格数据
    np.random.seed(42)
    base_price = 50000.0
    returns = np.random.normal(0.001, 0.02, periods)
    close = base_price * np.cumprod(1 + returns)
    
    # 生成 OHLCV 数据
    high = close * (1 + np.abs(np.random.normal(0, 0.01, periods)))
    low = close * (1 - np.abs(np.random.normal(0, 0.01, periods)))
    open_price = close * (1 + np.random.normal(0, 0.005, periods))
    volume = np.random.uniform(100, 1000, periods)
    
    df = pd.DataFrame({
        'timestamp': dates,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    })
    
    return df


class TestAlphaMetadata:
    """测试因子元数据"""
    
    def test_metadata_creation(self):
        """测试元数据创建"""
        meta = AlphaMetadata(
            name="test_factor",
            formula="test formula",
            universe="crypto_perp",
            column_dependencies=["close", "volume"],
            warmup_periods=20,
            description="Test factor"
        )
        
        assert meta.name == "test_factor"
        assert meta.formula == "test formula"
        assert meta.universe == "crypto_perp"
        assert meta.column_dependencies == ["close", "volume"]
        assert meta.warmup_periods == 20
        assert meta.description == "Test factor"
    
    def test_metadata_to_dict(self):
        """测试元数据转换为字典"""
        meta = AlphaMetadata(
            name="test_factor",
            formula="test formula",
            universe="crypto_perp",
            column_dependencies=["close"],
            warmup_periods=10
        )
        
        meta_dict = meta.to_dict()
        
        assert isinstance(meta_dict, dict)
        assert meta_dict['name'] == "test_factor"
        assert meta_dict['formula'] == "test formula"
        assert meta_dict['universe'] == "crypto_perp"
        assert meta_dict['column_dependencies'] == ["close"]
        assert meta_dict['warmup_periods'] == 10


class TestAlphaFactory:
    """测试因子工厂函数"""
    
    def test_get_all_alphas(self):
        """测试获取所有因子"""
        alphas = get_all_alphas()
        
        assert len(alphas) == 23
        assert all(hasattr(alpha, '__alpha_meta__') for alpha in alphas)
        assert all(hasattr(alpha, 'compute') for alpha in alphas)
    
    def test_get_alphas_by_category(self):
        """测试按类别获取因子"""
        momentum_alphas = get_alphas_by_category('momentum')
        volatility_alphas = get_alphas_by_category('volatility')
        volume_alphas = get_alphas_by_category('volume')
        mean_reversion_alphas = get_alphas_by_category('mean_reversion')
        
        assert len(momentum_alphas) == 5
        assert len(volatility_alphas) == 6
        assert len(volume_alphas) == 6
        assert len(mean_reversion_alphas) == 6
        
        # 测试无效类别
        invalid_alphas = get_alphas_by_category('invalid')
        assert len(invalid_alphas) == 0


class TestAlphaComputation:
    """测试因子计算"""
    
    def test_all_alphas_compute(self):
        """测试所有因子都能正常计算"""
        data = generate_test_data(100)
        alphas = get_all_alphas()
        
        for alpha_class in alphas:
            alpha = alpha_class()
            
            # 检查元数据
            assert hasattr(alpha, '__alpha_meta__')
            meta = alpha.__alpha_meta__
            assert isinstance(meta, AlphaMetadata)
            
            # 计算因子
            result = alpha.compute(data)
            
            # 检查结果
            assert isinstance(result, pd.Series)
            assert len(result) == len(data)
            
            # 检查是否有有效值（不是全 NaN）
            valid_count = result.notna().sum()
            assert valid_count > 0, f"{alpha_class.__name__} 计算结果全为 NaN"
            
            # 检查 warmup 期间后的值是否有效
            if meta.warmup_periods < len(data):
                post_warmup = result.iloc[meta.warmup_periods:]
                valid_post_warmup = post_warmup.notna().sum()
                assert valid_post_warmup > 0, f"{alpha_class.__name__} warmup 后全为 NaN"
    
    def test_alpha_with_insufficient_data(self):
        """测试数据不足时的行为"""
        data = generate_test_data(10)  # 只有 10 期数据
        alphas = get_all_alphas()
        
        for alpha_class in alphas:
            alpha = alpha_class()
            
            # 应该能正常计算，但可能返回全 NaN
            result = alpha.compute(data)
            assert isinstance(result, pd.Series)
            assert len(result) == len(data)
    
    def test_alpha_column_dependencies(self):
        """测试因子对列依赖的检查"""
        data = generate_test_data(100)
        alphas = get_all_alphas()
        
        for alpha_class in alphas:
            alpha = alpha_class()
            meta = alpha.__alpha_meta__
            
            # 检查所需列是否都在数据中
            for col in meta.column_dependencies:
                assert col in data.columns, f"{alpha_class.__name__} 需要列 {col}，但数据中没有"


class TestLookaheadGuard:
    """测试前视偏差防护"""
    
    def test_all_alphas_pass_lookahead_guard(self):
        """测试所有因子都通过前视偏差检查"""
        alphas = get_all_alphas()
        
        for alpha_class in alphas:
            passed = check_lookahead_bias(alpha_class)
            assert passed, f"{alpha_class.__name__} 未通过前视偏差检查"
    
    def test_lookahead_guard_detects_negative_shift(self):
        """测试前视偏差检查能检测到负数 shift"""
        # 创建一个有问题的因子类
        class BadAlpha:
            __alpha_meta__ = AlphaMetadata(
                name="bad_alpha",
                formula="test",
                universe="crypto_perp",
                column_dependencies=["close"],
                warmup_periods=0
            )
            
            def compute(self, data: pd.DataFrame) -> pd.Series:
                return data['close'].shift(-1)  # 前视偏差！
        
        passed = check_lookahead_bias(BadAlpha)
        assert not passed, "应该检测到负数 shift 的前视偏差"


class TestPurityGate:
    """测试 AST 纯度门检查"""
    
    def test_all_alphas_pass_purity_gate(self):
        """测试所有因子都通过纯度门检查"""
        alphas = get_all_alphas()
        
        for alpha_class in alphas:
            passed = check_purity(alpha_class)
            assert passed, f"{alpha_class.__name__} 未通过纯度门检查"
    
    def test_purity_gate_detects_forbidden_calls(self):
        """测试纯度门能检测到禁止的函数调用"""
        # 创建一个有问题的因子类
        class BadAlpha:
            __alpha_meta__ = AlphaMetadata(
                name="bad_alpha",
                formula="test",
                universe="crypto_perp",
                column_dependencies=["close"],
                warmup_periods=0
            )
            
            def compute(self, data: pd.DataFrame) -> pd.Series:
                return future_data(data['close'])  # 禁止的函数！
        
        passed = check_purity(BadAlpha)
        assert not passed, "应该检测到禁止的函数调用"


class TestAlphaQuality:
    """测试因子质量"""
    
    def test_all_alphas_have_metadata(self):
        """测试所有因子都有完整的元数据"""
        alphas = get_all_alphas()
        
        for alpha_class in alphas:
            alpha = alpha_class()
            meta = alpha.__alpha_meta__
            
            # 检查必填字段
            assert meta.name, f"{alpha_class.__name__} 缺少 name"
            assert meta.formula, f"{alpha_class.__name__} 缺少 formula"
            assert meta.universe, f"{alpha_class.__name__} 缺少 universe"
            assert meta.column_dependencies, f"{alpha_class.__name__} 缺少 column_dependencies"
            assert meta.warmup_periods >= 0, f"{alpha_class.__name__} warmup_periods 不能为负"
            assert meta.description, f"{alpha_class.__name__} 缺少 description"
    
    def test_alpha_names_are_unique(self):
        """测试因子名称唯一"""
        alphas = get_all_alphas()
        names = [alpha.__alpha_meta__.name for alpha in alphas]
        
        assert len(names) == len(set(names)), "存在重复的因子名称"
    
    def test_alpha_categories_coverage(self):
        """测试因子类别覆盖"""
        categories = ['momentum', 'volatility', 'volume', 'mean_reversion']
        
        for category in categories:
            alphas = get_alphas_by_category(category)
            assert len(alphas) > 0, f"类别 {category} 没有因子"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
