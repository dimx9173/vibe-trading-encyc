"""演化式因子公式搜尋 (Phase 3, 替代 RL — 修正註記 3.3).

對 StackVM AST 做變異/交叉, 用乾淨 PIT 評分選擇 (IC/IR/Sharpe).
無 lookahead: 因子值 t 期, forward return t+1 開盤.
"""
from __future__ import annotations

import random
from typing import Any, Callable, List, Optional, Tuple

from vibe_trading.factors.vm import ARITY

# 可用運算元
_OPS2 = ["ADD", "SUB", "MUL", "DIV", "GATE"]
_OPS1 = ["NEG", "ABS", "SIGN", "JUMP", "DECAY", "DELAY1", "MAX3"]


def _random_ast(
    features: List[str],
    depth: int = 0,
    max_depth: int = 4,
    rng=None,
) -> Any:
    """隨機生成公式 AST (深度控制)."""
    if rng is None:
        rng = random.Random()
    if depth >= max_depth or rng.random() < 0.4:
        return rng.choice(features)
    op = rng.choice(_OPS1 + _OPS2)
    arity = ARITY[op]
    args = [_random_ast(features, depth + 1, max_depth, rng) for _ in range(arity)]
    return [op] + args


def mutate(
    ast: Any,
    features: List[str],
    rng=None,
    max_depth: int = 4,
) -> Any:
    """變異: 隨機替換一個子樹或葉子."""
    if rng is None:
        rng = random.Random()
    if isinstance(ast, list) and len(ast) > 1 and rng.random() < 0.6:
        idx = rng.randint(1, len(ast) - 1)
        out = ast.copy()
        out[idx] = _random_ast(features, 1, max_depth, rng)
        return out
    return _random_ast(features, 0, max_depth, rng)


def _pick_subtree(node: Any, rng: random.Random) -> Any:
    """隨機選取子樹."""
    if isinstance(node, list) and len(node) > 1 and rng.random() < 0.6:
        idx = rng.randint(1, len(node) - 1)
        return _pick_subtree(node[idx], rng)
    return node


def crossover(a: Any, b: Any, rng: Optional[random.Random] = None) -> Any:
    """交叉: 交換隨機子樹."""
    if rng is None:
        rng = random.Random()
    sa = _pick_subtree(a, rng)
    sb = _pick_subtree(b, rng)
    out = a.copy() if isinstance(a, list) else a
    if isinstance(out, list) and len(out) > 1:
        out[1] = sb if rng.random() < 0.5 else sa
    return out


def evolve(
    features: List[str],
    fitness_fn: Callable[[Any], Optional[float]],
    population: int = 50,
    generations: int = 20,
    seed: int = 42,
    top_k: int = 10,
) -> List[Tuple[Any, float]]:
    """演化搜尋: 初始隨機池 → 選擇 top-K → 變異/交叉 → 下一代.

    Args:
        features: 可用特徵名 (系列名)
        fitness_fn: 評分函式, 回傳 fitness (None/NaN → 淘汰)
        population: 每代池大小
        generations: 迭代代數
        seed: 隨機種子 (確定性)
        top_k: 回傳候選數

    Returns:
        [(ast, fitness)] 按 fitness 降序
    """
    rng = random.Random(seed)
    pool: List[Any] = [_random_ast(features, rng=rng) for _ in range(population)]
    best: List[Tuple[Any, float]] = []

    for _ in range(generations):
        scored: List[Tuple[Any, float]] = []
        for ast in pool:
            f = fitness_fn(ast)
            if f is not None and f == f:  # 非 None 非 NaN
                scored.append((ast, f))
        scored.sort(key=lambda x: -x[1])
        best = scored[:top_k]

        # 下一代: 精英 + 變異 + 交叉
        next_pool = [a for a, _ in best]
        while len(next_pool) < population:
            if best and rng.random() < 0.6:
                parent = rng.choice([a for a, _ in best])
                next_pool.append(mutate(parent, features, rng))
            elif len(best) >= 2:
                a, b = rng.sample([x for x, _ in best], 2)
                next_pool.append(crossover(a, b, rng))
            else:
                next_pool.append(_random_ast(features, rng=rng))
        pool = next_pool

    # 最終評分
    final: List[Tuple[Any, float]] = []
    for ast in pool:
        f = fitness_fn(ast)
        if f is not None and f == f:
            final.append((ast, f))
    final.sort(key=lambda x: -x[1])
    return final[:top_k]
