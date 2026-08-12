"""AST Purity Gate - AST 纯度门检查

通过静态代码分析确保因子实现中没有使用未来数据。
"""
import ast
import inspect
import textwrap
from typing import List, Dict, Any, Set
from dataclasses import dataclass


@dataclass
class PurityViolation:
    """纯度违规"""
    factor_name: str
    line_number: int
    violation_type: str
    description: str
    severity: str  # 'error' | 'warning'


class ASTPurityGate:
    """AST 纯度门检查器
    
    通过静态代码分析检测因子实现中的潜在问题。
    """
    
    # 禁止的函数调用
    FORBIDDEN_CALLS: Dict[str, str] = {
        'future_data': '禁止使用未来数据函数',
        'look_ahead': '禁止使用前视函数',
        'peek': '禁止使用 peek 函数',
    }
    
    # 需要警告的模式
    WARNING_PATTERNS: Dict[str, str] = {
        'global': '避免使用全局变量，可能导致状态污染',
        'nonlocal': '避免使用 nonlocal，可能导致状态污染',
    }
    
    def __init__(self):
        self.violations: List[PurityViolation] = []
    
    def check_factor(self, factor_class: type) -> List[PurityViolation]:
        """检查因子类的纯度
        
        Args:
            factor_class: 因子类
            
        Returns:
            违规列表
        """
        self.violations = []
        
        # 获取 compute 方法的源代码
        if not hasattr(factor_class, 'compute'):
            return self.violations
        source = textwrap.dedent(inspect.getsource(factor_class.compute))

        
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            self.violations.append(PurityViolation(
                factor_name=factor_class.__name__,
                line_number=0,
                violation_type='syntax_error',
                description=f'代码语法错误: {e}',
                severity='error'
            ))
            return self.violations
        
        # 遍历 AST 节点
        for node in ast.walk(tree):
            self._check_node(node, factor_class.__name__)
        
        return self.violations
    
    def _check_node(self, node: ast.AST, factor_name: str) -> None:
        """检查单个 AST 节点
        
        Args:
            node: AST 节点
            factor_name: 因子名称
        """
        # 检查函数调用
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                if func_name in self.FORBIDDEN_CALLS:
                    self.violations.append(PurityViolation(
                        factor_name=factor_name,
                        line_number=node.lineno,
                        violation_type='forbidden_call',
                        description=self.FORBIDDEN_CALLS[func_name],
                        severity='error'
                    ))
        
        # 检查全局和非局部变量
        if isinstance(node, ast.Global):
            self.violations.append(PurityViolation(
                factor_name=factor_name,
                line_number=node.lineno,
                violation_type='global_variable',
                description=self.WARNING_PATTERNS['global'],
                severity='warning'
            ))
        
        if isinstance(node, ast.Nonlocal):
            self.violations.append(PurityViolation(
                factor_name=factor_name,
                line_number=node.lineno,
                violation_type='nonlocal_variable',
                description=self.WARNING_PATTERNS['nonlocal'],
                severity='warning'
            ))
        
        # 检查赋值语句中的潜在问题
        if isinstance(node, ast.Assign):
            # 检查是否在修改外部作用域的变量
            for target in node.targets:
                if isinstance(target, ast.Attribute):
                    # 检查是否在修改 self 的属性（除了 __alpha_meta__）
                    if isinstance(target.value, ast.Name) and target.value.id == 'self':
                        if target.attr != '__alpha_meta__':
                            self.violations.append(PurityViolation(
                                factor_name=factor_name,
                                line_number=node.lineno,
                                violation_type='state_modification',
                                description=f'避免在 compute 中修改实例状态: self.{target.attr}',
                                severity='warning'
                            ))
    
    def check_all_factors(self, factor_classes: List[type]) -> Dict[str, Any]:
        """检查所有因子的纯度
        
        Args:
            factor_classes: 因子类列表
            
        Returns:
            检查结果字典
        """
        results: Dict[str, Any] = {
            'total_factors': len(factor_classes),
            'passed': 0,
            'failed': 0,
            'warnings': 0,
            'violations': []
        }
        
        for factor_class in factor_classes:
            violations = self.check_factor(factor_class)
            
            errors = [v for v in violations if v.severity == 'error']
            warnings = [v for v in violations if v.severity == 'warning']
            
            if errors:
                results['failed'] += 1
                results['violations'].extend(violations)
            else:
                results['passed'] += 1
                results['warnings'] += len(warnings)
                if warnings:
                    results['violations'].extend(warnings)
        
        return results


def check_purity(factor_class: type) -> bool:
    """检查因子的纯度
    
    Args:
        factor_class: 因子类
        
    Returns:
        True 表示通过检查，False 表示存在错误
    """
    gate = ASTPurityGate()
    violations = gate.check_factor(factor_class)
    errors = [v for v in violations if v.severity == 'error']
    return len(errors) == 0


def check_all_purity(factor_classes: List[type]) -> Dict[str, Any]:
    """检查所有因子的纯度
    
    Args:
        factor_classes: 因子类列表
        
    Returns:
        检查结果字典
    """
    gate = ASTPurityGate()
    return gate.check_all_factors(factor_classes)
