"""Lookahead Guard - 前视偏差防护

检测因子实现中是否存在使用前视数据的问题。
"""
import ast
import inspect
import textwrap
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class LookaheadViolation:
    """前视偏差违规"""
    factor_name: str
    line_number: int
    violation_type: str
    description: str


class LookaheadGuard:
    """前视偏差防护器
    
    通过 AST 分析检测因子实现中是否使用了未来数据。
    """
    
    # 危险的方法调用（可能导致前视偏差）
    DANGEROUS_METHODS: Dict[str, str] = {
        'shift': 'shift() 可能引入前视偏差，确保参数为正数',
        'rolling': 'rolling() 窗口操作需确保不使用未来数据',
        'expanding': 'expanding() 需确保不使用未来数据',
        'cumsum': 'cumsum() 需确保不使用未来数据',
        'cumprod': 'cumprod() 需确保不使用未来数据',
    }
    
    # 禁止的模式
    FORBIDDEN_PATTERNS: Dict[str, str] = {
        'iloc[::-1]': '反转序列可能引入前视偏差',
        'loc[::-1]': '反转序列可能引入前视偏差',
        '[::-1]': '反转序列可能引入前视偏差',
    }
    
    def check_factor(self, factor_class: type) -> List[LookaheadViolation]:
        """检查因子类是否存在前视偏差
        
        Args:
            factor_class: 因子类
            
        Returns:
            违规列表
        """
        violations: List[LookaheadViolation] = []
        
        # 获取 compute 方法的源代码
        if not hasattr(factor_class, 'compute'):
            return violations
            
        source = textwrap.dedent(inspect.getsource(factor_class.compute))
        
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return violations
        
        # 检查危险的方法调用
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    method_name = node.func.attr
                    
                    if method_name in self.DANGEROUS_METHODS:
                        # 检查 shift 的参数
                        if method_name == 'shift':
                            if node.args:
                                arg = node.args[0]
                                # 检查负数常量（如 shift(-1)）
                                if isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float)) and arg.value < 0:
                                    violations.append(LookaheadViolation(
                                        factor_name=factor_class.__name__,
                                        line_number=node.lineno,
                                        violation_type='negative_shift',
                                        description='shift() 使用负数参数会引入前视偏差'
                                    ))
                                # 检查一元运算符（如 shift(-n)）
                                elif isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub):
                                    violations.append(LookaheadViolation(
                                        factor_name=factor_class.__name__,
                                        line_number=node.lineno,
                                        violation_type='negative_shift',
                                        description='shift() 使用负数参数会引入前视偏差'
                                    ))
                        
                        # 其他危险方法只记录警告
                        elif method_name in ['rolling', 'expanding', 'cumsum', 'cumprod']:
                            violations.append(LookaheadViolation(
                                factor_name=factor_class.__name__,
                                line_number=node.lineno,
                                violation_type='dangerous_method',
                                description=f'{method_name}() 需要确保不使用未来数据'
                            ))
        
        # 检查禁止的模式
        for pattern, description in self.FORBIDDEN_PATTERNS.items():
            if pattern in source:
                violations.append(LookaheadViolation(
                    factor_name=factor_class.__name__,
                    line_number=0,  # 无法确定具体行号
                    violation_type='forbidden_pattern',
                    description=description
                ))
        
        return violations
    
    def check_all_factors(self, factor_classes: List[type]) -> Dict[str, Any]:
        """检查所有因子
        
        Args:
            factor_classes: 因子类列表
            
        Returns:
            检查结果字典
        """
        results: Dict[str, Any] = {
            'total_factors': len(factor_classes),
            'passed': 0,
            'failed': 0,
            'violations': []
        }
        
        for factor_class in factor_classes:
            violations = self.check_factor(factor_class)
            
            if violations:
                results['failed'] += 1
                results['violations'].extend(violations)
            else:
                results['passed'] += 1
        
        return results

def check_lookahead_bias(factor_class: type) -> bool:
    """检查因子是否存在前视偏差

    Args:
        factor_class: 因子类

    Returns:
        True 表示通过检查，False 表示存在前视偏差
    """
    guard = LookaheadGuard()
    violations = guard.check_factor(factor_class)
    # 只有 negative_shift 才是真正的前视偏差；rolling/cumsum 等是 warning
    return not any(v.violation_type == 'negative_shift' for v in violations)



def check_all_lookahead_bias(factor_classes: List[type]) -> Dict[str, Any]:
    """检查所有因子的前视偏差
    
    Args:
        factor_classes: 因子类列表
        
    Returns:
        检查结果字典
    """
    guard = LookaheadGuard()
    return guard.check_all_factors(factor_classes)
