"""
Macro Analysis Agent

Analyzes macro environment (trends, sentiment, major events).
"""

from typing import Dict, Optional
from datetime import datetime

from pi_agent_core import Agent, AgentOptions
from vibe_trading.config.llm_config import get_model_from_config, make_get_api_key
from pi_logger import get_logger

from vibe_trading.config.agent_config import AgentConfig, AgentRole
from vibe_trading.config.settings import get_settings
from vibe_trading.agents.agent_factory import ToolContext
from vibe_trading.agents.llm_content import prompt_with_timeout
from vibe_trading.data_sources.macro_storage import MacroState

logger = get_logger(__name__)


class MacroAnalysisAgent:
    """
    Macro analysis agent

    Analyzes the macro environment including:
    - Market trends and direction
    - Market sentiment
    - Major events and news
    - Overall market regime
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        """
        Initialize macro analysis agent

        Args:
            config: Agent configuration (optional, uses default if not provided)
        """
        if config is None:
            config = AgentConfig(
                role=AgentRole.BULL_RESEARCHER,  # Use researcher role
                name="MacroAnalysisAgent",
                model=get_settings().llm_config_name,
            )

        self.config = config
        self._system_prompt = self._get_macro_prompt()
        self._agent: Optional[Agent] = None
        self._tool_context: Optional[ToolContext] = None

    def _get_macro_prompt(self) -> str:
        """Get macro-specific system prompt"""
        return """You are a Macro Analysis Agent for cryptocurrency trading.

Your role is to analyze the macro environment and provide a comprehensive assessment of market conditions.

MACRO ANALYSIS FRAMEWORK:

1. TREND ANALYSIS
   - Direction: UPTREND / DOWNTREND / SIDEWAYS
   - Strength: STRONG / MODERATE / WEAK
   - Market Regime: BULL / BEAR / NEUTRAL

2. SENTIMENT ANALYSIS
   - Overall: POSITIVE / NEGATIVE / NEUTRAL
   - Score: -100 to 100 (negative to positive)
   - Key drivers: Fear/greed, news sentiment, social sentiment

3. MAJOR EVENTS
   - Regulatory changes
   - Institutional adoption
   - Major partnerships
   - Market-moving news
   - Geopolitical events

4. RECOMMENDATION
   - Suggested stance: LONG/NEUTRAL/SHORT
   - Confidence level: 0.0 to 1.0
   - Key factors influencing recommendation

ANALYSIS PRINCIPLES:
- Focus on the big picture, not short-term noise
- Consider multiple data sources and timeframes
- Be objective and data-driven
- Provide clear, actionable insights
- Acknowledge uncertainty when present

IMPORTANT OUTPUT FORMAT:
The FIRST TWO LINES of your response must be EXACTLY:

REGIME: RISK_ON|NEUTRAL|RISK_OFF
REGIME_DETAIL: CHOPPY|TRENDING|UNCERTAIN

(RISK_ON = risk-on / bullish; RISK_OFF = risk-off / strong downtrend; NEUTRAL = mixed)
(REGIME_DETAIL discrete 3档: CHOPPY=震荡/低波动挤压, TRENDING=趋势延续, UNCERTAIN=不确定)
Constraint: CHOPPY→qty↓ threshold↑ (only de-risk, never add qty), TRENDING→maintain.
Then provide the full analysis below (your detailed "Market Regime: BULL/BEAR/NEUTRAL" line still goes in the TREND ANALYSIS section).

When providing your analysis, structure it clearly with:
1. TREND ANALYSIS section
2. SENTIMENT ANALYSIS section
3. MAJOR EVENTS section
4. RECOMMENDATION section
5. CONFIDENCE score

Your analysis should help guide trading decisions by providing context about the overall market environment."""

    async def initialize(
        self, tool_context: ToolContext, enable_streaming: bool = False
    ) -> None:
        """
        Initialize agent

        Args:
            tool_context: Tool context
            enable_streaming: Whether to enable streaming
        """
        self._tool_context = tool_context

        # Get model
        model = get_model_from_config(self.config.model)

        # Create agent with macro prompt
        agent_options = AgentOptions(
            initial_state={
                "system_prompt": self._system_prompt,
                "model": model,
            },
            get_api_key=make_get_api_key(),
        )

        self._agent = Agent(agent_options)
        logger.info("MacroAnalysisAgent initialized")

    async def analyze(self, market_data: Dict) -> Dict:
        """
        Perform macro analysis

        Args:
            market_data: Market data including sentiment, trends, events

        Returns:
            Analysis result dictionary
        """
        if not self._agent:
            raise RuntimeError("Agent not initialized. Call initialize() first.")

        # Clear previous messages for fresh analysis
        # Fix 2026-08-10 (SWDA): pi-py Agent 無 clear_messages API — 其他 agent 都用
        # reset()（清 messages + streaming/error/tool_calls + queues），macro 是遷移漏網。
        self._agent.reset()

        # Build analysis prompt
        prompt = self._build_analysis_prompt(market_data)

        # Send prompt to agent（含 timeout 防 thinking loop）
        ok = await prompt_with_timeout(self._agent, prompt)
        if not ok:
            logger.warning("MacroAgent LLM timeout (120s)", tag="Macro")
            return "Macro analysis failed - LLM timeout (120s)"

        # Wait for agent to complete
        await self._agent.wait_for_idle()

        # Get response from agent message history
        messages = self._agent.state.messages
        if messages:
            # Get the last assistant message
            last_message = messages[-1]
            if hasattr(last_message, "content"):
                # Extract text from message content
                response_text = ""
                for content in last_message.content:
                    if hasattr(content, "text"):
                        response_text += content.text

                # 记录宏观分析完整响应到日志
                logger.info(f"Macro Analysis Response: {response_text}", tag="Macro")

                # Parse response
                analysis = self._parse_analysis(response_text)

                logger.info(
                    f"Macro analysis completed: {analysis['market_regime']} (confidence={analysis['confidence']:.2f})"
                )
                return analysis

        # Return default analysis if no response
        logger.warning("No response from agent, returning default analysis")
        return {
            "trend_direction": "SIDEWAYS",
            "trend_strength": "MODERATE",
            "market_regime": "NEUTRAL",
            "overall_sentiment": "NEUTRAL",
            "sentiment_score": 0.0,
            "major_events": [],
            "recommendation": {
                "stance": "NEUTRAL",
                "rationale": "Unable to get agent response",
            },
            "confidence": 0.0,
        }

    def _build_analysis_prompt(self, market_data: Dict) -> str:
        """Build analysis prompt"""
        prompt = """MACRO ANALYSIS REQUEST
======================

Please analyze the following market data and provide a comprehensive macro assessment.

MARKET DATA:
"""

        # Add fear/greed index
        if "fear_greed" in market_data:
            fg = market_data["fear_greed"]
            prompt += f"""
Fear & Greed Index: {fg.get("value", "N/A")} ({fg.get("valueClassification", "N/A")})
"""

        # Add funding rates
        if "funding_rate" in market_data:
            fr = market_data["funding_rate"]
            prompt += f"""
Funding Rate: {fr.get("lastFundingRate", "N/A")}
"""

        # Add 24h ticker
        if "ticker_24h" in market_data:
            ticker = market_data["ticker_24h"]
            prompt += f"""
24h Price Change: {ticker.get("priceChangePercent", "N/A")}%
24h Volume: {ticker.get("volume", "N/A")}
24h Trades: {ticker.get("count", "N/A")}
"""

        # Add trending symbols
        if "trending" in market_data:
            trending = market_data["trending"]
            prompt += f"""
Trending Symbols: {trending[:5] if isinstance(trending, list) else trending}
"""

        klines = market_data.get("klines_24h")
        if klines:
            interval = market_data.get("klines_24h_interval", "30m")
            hours = market_data.get("klines_24h_hours", 24)
            prompt += f"\n24h KLINES ({interval}, last {hours}h, {len(klines)} bars, oldest→newest):\n"
            cap = max(1, int(hours * 60 / 30)) if interval == "30m" else len(klines)
            for k in klines[-cap:]:
                prompt += (
                    f"  t={k.get('t', 0)} o={k.get('o', 0):.2f} h={k.get('h', 0):.2f} "
                    f"l={k.get('l', 0):.2f} c={k.get('c', 0):.2f} v={k.get('v', 0):.2f}\n"
                )

        # Add any additional data
        if "additional_data" in market_data:
            prompt += f"""
Additional Data:
{market_data["additional_data"]}
"""

        prompt += """
Please provide your analysis in the following format:

REGIME: [RISK_ON/NEUTRAL/RISK_OFF]  (first line, exactly this)
REGIME_DETAIL: [CHOPPY|TRENDING|UNCERTAIN]  (second line, exactly this)

TREND ANALYSIS:
Direction: [UPTREND/DOWNTREND/SIDEWAYS]
Strength: [STRONG/MODERATE/WEAK]
Market Regime: [BULL/BEAR/NEUTRAL]

SENTIMENT ANALYSIS:
Overall: [POSITIVE/NEGATIVE/NEUTRAL]
Score: [-100 to 100]
Key Drivers: [brief explanation]

MAJOR EVENTS:
[list any major events or None]

RECOMMENDATION:
Stance: [LONG/NEUTRAL/SHORT]
Rationale: [brief explanation]

CONFIDENCE: [0.0-1.0]

DISCRETE CONSTRAINT: CHOPPY→qty↓ threshold↑ (only de-risk), TRENDING→maintain.
"""

        return prompt

    def _parse_analysis(self, response: str) -> Dict:
        """
        Parse agent response into analysis dictionary

        Args:
            response: Agent response text

        Returns:
            Analysis dictionary
        """
        lines = response.strip().split("\n")

        analysis = {
            "trend_direction": "SIDEWAYS",
            "trend_strength": "MODERATE",
            "market_regime": "NEUTRAL",
            "regime_detail": "UNCERTAIN",
            "overall_sentiment": "NEUTRAL",
            "sentiment_score": 0.0,
            "major_events": [],
            "recommendation": {
                "stance": "NEUTRAL",
                "rationale": "",
            },
            "confidence": 0.5,
        }

        current_section = None
        regime_locked = False

        for line in lines:
            line = line.strip()

            if line.upper().startswith("REGIME_DETAIL:"):
                v = line.split(":", 1)[1].strip().upper()
                analysis["regime_detail"] = v if v in ("CHOPPY", "TRENDING", "UNCERTAIN") else "UNCERTAIN"
                continue

            if line.upper().startswith("REGIME:"):
                value = line.split(":", 1)[1].strip().upper()
                if value in ("RISK_ON", "NEUTRAL", "RISK_OFF"):
                    analysis["market_regime"] = value
                    regime_locked = True

            # Detect sections
            if line.startswith("TREND ANALYSIS:"):
                current_section = "trend"
            elif line.startswith("SENTIMENT ANALYSIS:"):
                current_section = "sentiment"
            elif line.startswith("MAJOR EVENTS:"):
                current_section = "events"
            elif line.startswith("RECOMMENDATION:"):
                current_section = "recommendation"

            # Parse fields
            elif line.startswith("Direction:"):
                analysis["trend_direction"] = line.split(":", 1)[1].strip().upper()
            elif line.startswith("Strength:"):
                analysis["trend_strength"] = line.split(":", 1)[1].strip().upper()
            elif line.startswith("Market Regime:"):
                if not regime_locked:
                    analysis["market_regime"] = line.split(":", 1)[1].strip().upper()
            elif line.startswith("Overall:"):
                analysis["overall_sentiment"] = line.split(":", 1)[1].strip().upper()
            elif line.startswith("Score:"):
                try:
                    analysis["sentiment_score"] = float(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith("Stance:"):
                analysis["recommendation"]["stance"] = (
                    line.split(":", 1)[1].strip().upper()
                )
            elif line.startswith("Rationale:"):
                analysis["recommendation"]["rationale"] = line.split(":", 1)[1].strip()
            elif line.startswith("CONFIDENCE:"):
                try:
                    analysis["confidence"] = float(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif current_section == "events" and line and not line.startswith("-"):
                # Parse major events
                if line.lower() != "none":
                    analysis["major_events"].append(line)

        return analysis

    async def create_macro_state(
        self, symbol: str, analysis: Dict, analysis_duration: float = 0.0
    ) -> MacroState:
        """
        Create MacroState from analysis

        Args:
            symbol: Trading symbol
            analysis: Analysis result
            analysis_duration: Time taken for analysis

        Returns:
            MacroState instance
        """
        rd = str(analysis.get("regime_detail", "UNCERTAIN") or "UNCERTAIN").strip().upper()
        if rd not in ("CHOPPY", "TRENDING", "UNCERTAIN"):
            rd = "UNCERTAIN"
        return MacroState(
            symbol=symbol,
            timestamp=int(datetime.now().timestamp() * 1000),
            trend_direction=analysis.get("trend_direction", "SIDEWAYS"),
            trend_strength=analysis.get("trend_strength", "MODERATE"),
            market_regime=analysis.get("market_regime", "NEUTRAL"),
            regime_detail=rd,
            overall_sentiment=analysis.get("overall_sentiment", "NEUTRAL"),
            sentiment_score=analysis.get("sentiment_score", 0.0),
            major_events=analysis.get("major_events", []),
            agent_recommendation=analysis.get("recommendation", {}),
            confidence=analysis.get("confidence", 0.5),
            analysis_duration=analysis_duration,
        )
