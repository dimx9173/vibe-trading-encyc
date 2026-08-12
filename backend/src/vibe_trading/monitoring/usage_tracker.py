"""Usage tracking integration for LLM calls."""
import logging
from typing import Any

from .usage_ledger import get_usage_ledger

logger = logging.getLogger(__name__)


async def track_llm_usage(
    agent_name: str,
    model: str,
    symbol: str,
    agent: Any,
) -> None:
    """Extract usage data from agent's last message and record to ledger.

    Args:
        agent_name: Name of the agent (e.g., "technical_analyst")
        model: Model name (e.g., "deepseek-v3")
        symbol: Trading symbol (e.g., "BTCUSDT")
        agent: pi_agent_core Agent instance
    """
    try:
        # Get the last assistant message
        messages = getattr(agent.state, "messages", [])
        if not messages:
            return

        # Find the last assistant message
        last_assistant = None
        for msg in reversed(messages):
            if getattr(msg, "role", None) == "assistant":
                last_assistant = msg
                break

        if not last_assistant:
            return

        # Extract usage data
        usage = getattr(last_assistant, "usage", None)
        if not usage:
            logger.debug(f"No usage data found for {agent_name}")
            return

        input_tokens = getattr(usage, "input", 0)
        output_tokens = getattr(usage, "output", 0)

        if input_tokens == 0 and output_tokens == 0:
            logger.debug(f"Zero tokens reported for {agent_name}")
            return

        # Estimate cost (simplified - real pricing would need model-specific rates)
        # Using average rates: $0.01 per 1K input tokens, $0.03 per 1K output tokens
        cost_usd = (input_tokens / 1000 * 0.01) + (output_tokens / 1000 * 0.03)

        # Record to ledger
        ledger = get_usage_ledger()
        await ledger.record_usage(
            agent_name=agent_name,
            model=model,
            symbol=symbol,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )

        logger.debug(
            f"Recorded usage for {agent_name}: "
            f"input={input_tokens}, output={output_tokens}, cost=${cost_usd:.4f}"
        )

    except Exception as e:
        # Don't let usage tracking break the main flow
        logger.warning(f"Failed to track usage for {agent_name}: {e}")
