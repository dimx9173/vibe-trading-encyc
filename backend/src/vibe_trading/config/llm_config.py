"""
LLM 配置管理（应用层）

从 ``vibe_trading/config/llm.yaml`` 加载模型配置，构造 pi-py 的 :class:`pi_ai.Model`。

设计说明
--------
pi-py 的 ``pi_ai`` 删除了 YAML 配置层（``config.py``）和 ``ModelRouter``，改为代码内
``register_model()`` + 直接传递 ``Model`` 实例。本项目仍保留 ``llm.yaml`` 作为模型定义的
单一来源（运维友好、无需改代码即可切换模型），但路由层（``ModelRouter`` /
``agent_model_mapping``）已移除——它在本项目里长期处于"半失效"状态（没有任何调用点传入
``agent_role``，映射表从未被读取）。

每个 YAML 条目的字段映射到 pi-py Model：

    provider: openai|anthropic   -> Model.api = "openai-completions" | "anthropic-messages"
    model:    <model_id>         -> Model.id
    base_url: <url>              -> Model.base_url
    api_key:  <literal|${ENV}>   -> 不进 Model；由 get_api_key_for(name) 返回，
                                    通过 AgentOptions(get_api_key=...) 注入

对于 OpenAI 兼容端点（longcat / iflow / deepseek / aliyun / opencode-zen 等），
统一使用 ``api = "openai-completions"`` + 自定义 ``base_url``。

安全提示：``llm.yaml`` 历史上包含明文 API key（longcat / iflow / glm_4_7 / aliyun_* /
opencode-zen）。这些 key 已在 git 历史中，轮换需另行处理，不在本次迁移范围内。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml

from pi_ai import Model

try:
    from pi_logger import get_logger

    logger = get_logger("LLMConfig")
except Exception:  # pragma: no cover - logger 可选
    import logging

    logger = logging.getLogger("LLMConfig")


# YAML provider 名 -> pi-py 注册的 API provider key
_PROVIDER_TO_API: Dict[str, str] = {
    "openai": "openai-completions",
    "anthropic": "anthropic-messages",
    # google / ollama 等暂无对应 pi-py provider，遇到时按 openai-completions 兼容处理
}


def _default_config_path() -> str:
    """默认配置文件路径：本模块同目录下的 llm.yaml。"""
    return str(Path(__file__).parent / "llm.yaml")


def _resolve_api_key(raw: str, provider: str) -> Optional[str]:
    """解析 api_key 字段，支持 ``${VAR}`` / ``${VAR:default}`` / 环境变量回退。"""
    if not raw:
        # 空值时按 provider 回退到常见环境变量
        env_fallback = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
        }.get(provider)
        return os.environ.get(env_fallback) if env_fallback else None

    # ${VAR} 或 ${VAR:default}
    if "${" in raw:
        inner = raw.split("${", 1)[1].split("}", 1)[0]
        var_name, _, default = inner.partition(":")
        return os.environ.get(var_name, default)

    return raw


class LLMConfig:
    """LLM 配置管理器。"""

    def __init__(self, config_path: Optional[str] = None):
        self._config: Dict[str, Any] = {}
        self._config_path = config_path or _default_config_path()
        self.load(self._config_path)

    def load(self, config_path: str) -> None:
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"配置文件不存在: {config_path}")
            return
        with open(path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f) or {}
        logger.info(f"加载 LLM 配置: {config_path}")
        logger.debug(f"可用模型: {list(self._config.get('llms', {}).keys())}")

    def get_current_name(self) -> str:
        return self._config.get("use_llm", "glm_4_7")

    def get_config(self, name: Optional[str] = None) -> Dict[str, Any]:
        name = name or self.get_current_name()
        llms = self._config.get("llms", {})
        if name not in llms:
            raise ValueError(
                f"LLM 配置不存在: {name}\n可用配置: {list(llms.keys())}"
            )
        return llms[name]

    def get_model(self, name: Optional[str] = None) -> Model:
        """根据配置名构造 pi-py :class:`Model`。"""
        name = name or self.get_current_name()
        cfg = self.get_config(name)

        provider = cfg.get("provider", "openai")
        api = _PROVIDER_TO_API.get(provider, "openai-completions")
        model_id = cfg.get("model", "gpt-4o")
        base_url = cfg.get("base_url", "")

        return Model(
            id=model_id,
            name=cfg.get("description", model_id) or model_id,
            api=api,
            provider=provider,
            base_url=base_url,
            input=["text"],
            context_window=0,
            max_tokens=0,
        )

    def get_api_key(self, name: Optional[str] = None) -> Optional[str]:
        """返回配置对应的 api_key（不放入 Model）。"""
        cfg = self.get_config(name)
        return _resolve_api_key(cfg.get("api_key", ""), cfg.get("provider", "openai"))

    def list_configs(self) -> Dict[str, str]:
        llms = self._config.get("llms", {})
        return {n: c.get("description", n) for n, c in llms.items()}

    @property
    def is_loaded(self) -> bool:
        return bool(self._config)


# =============================================================================
# 全局单例 + 便捷函数（保持原 pi_ai.config 的公开 API）
# =============================================================================

_default_config: Optional[LLMConfig] = None


def get_llm_config(config_path: Optional[str] = None) -> LLMConfig:
    """获取全局 LLMConfig 单例。"""
    global _default_config
    if _default_config is None:
        _default_config = LLMConfig(config_path)
    return _default_config


def get_model_from_config(name: Optional[str] = None) -> Model:
    """从配置构造 Model。与原 ``pi_ai.config.get_model_from_config`` 同名同义。"""
    return get_llm_config().get_model(name)


def get_api_key_from_config(name: Optional[str] = None) -> Optional[str]:
    """从配置读取 api_key。"""
    return get_llm_config().get_api_key(name)


def make_get_api_key() -> Callable[[str], Optional[str]]:
    """构造一个 ``AgentOptions(get_api_key=...)`` 可用的回调。

    回调签名 ``(provider: str) -> str | None``：根据 provider 名查当前默认模型的 key。
    用于把 yaml 里的 key 注入到 pi-py 的 stream 调用链。
    """
    cfg = get_llm_config()
    current = cfg.get_current_name()

    def _get_api_key(provider: str) -> Optional[str]:
        # provider 来自 Model.provider；直接用当前配置的 key
        return cfg.get_api_key(current)

    return _get_api_key
