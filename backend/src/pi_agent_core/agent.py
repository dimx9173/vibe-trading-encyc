"""
Agent class that uses the agent-loop directly.
No transport abstraction - calls the stream function via the loop.

Mirrors agent.ts from the TypeScript implementation.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from typing import Any

from .agent_loop import agent_loop, agent_loop_continue
from .types import (
    AgentContext,
    AgentEndEvent,
    AgentEvent,
    AgentLoopConfig,
    AgentState,
    AgentTool,
    AssistantMessage,
    ImageContent,
    Message,
    Model,
    StreamFn,
    TextContent,
    ThinkingBudgets,
    ThinkingContent,
    ThinkingLevel,
    ToolCall,
    Transport,
    UserMessage,
)


def _default_convert_to_llm(messages: list[Message]) -> list[Message]:
    """Default convertToLlm: Keep only LLM-compatible messages."""
    return [m for m in messages if hasattr(m, "role") and m.role in ("user", "assistant", "toolResult")]


def _get_default_stream_fn() -> "StreamFn":
    """Lazy-load pi_ai.stream_simple and wrap it as a StreamFn-compatible callable.

    原因：原本 AgentOptions.stream_fn 預設為 None，導致 agent_loop 內部
    raise ValueError，被 Agent.run() 的 except 吃掉，產生空內容訊息。
    這個 helper 提供一個能用的預設 stream_fn，wrap pi_ai.stream_simple 的回傳
    (StreamResponse) 成為 agent_loop 期望的 {"events": AsyncIterator, "result": async callable} 形狀。

    使用 lazy import 避免 pi_agent_core → pi_ai 的循環依賴 (pi_ai 內部有 import pi_agent_core)。
    """
    from pi_ai.enhanced_stream import stream_simple_with_retry
    from pi_ai.retry_handler import TimeoutConfig

    # agent_loop 呼叫方式：stream_fn(config.model, llm_context, stream_options)
    # stream_options 是 SimpleStreamOptions Pydantic model，所以要收第 3 個 positional 或 kwarg。
    async def _stream_fn(
        model: "Model",
        context: Any,
        options: Any = None,
        **kwargs: Any,
    ) -> dict:
        # AgentContext 是 Pydantic model，stream_simple 用 .get(...) 取值需要 dict。
        # 為了避免把 Message 物件序列化掉（會變 dict，後續 provider.stream() 會壞），
        # 手動組裝 dict 並保留 Message 物件原樣。
        if hasattr(context, "messages") and not isinstance(context, dict):
            ctx_dict = {
                "system_prompt": getattr(context, "system_prompt", ""),
                "messages": context.messages,
                "tools": getattr(context, "tools", None),
            }
        elif isinstance(context, dict):
            ctx_dict = context
        else:
            ctx_dict = vars(context)

        # 把 SimpleStreamOptions 攤平為 kwargs（給 stream_simple_with_retry）。
        # 需要過濾掉 pi_agent_core 特有的欄位（不是 OpenAI API 的合法參數）。
        _PI_AGENT_CORE_ONLY = {
            "transport",
            "thinking_budgets",
            "max_retry_delay_ms",
            "cancel_event",
            # excluded_keys 已含: signal, api_key, session_id, user_id, project_id
        }
        merged_opts: dict = dict(kwargs)
        if options is not None:
            if hasattr(options, "model_dump"):
                dumped = options.model_dump(exclude_none=True)
            elif hasattr(options, "__dict__"):
                dumped = dict(vars(options))
            else:
                dumped = {}
            for k in _PI_AGENT_CORE_ONLY:
                dumped.pop(k, None)
            merged_opts.update(dumped)

        # 用帶 retry + timeout 的版本，避免 opencode.ai streaming 連線 hang 時卡死整個決策。
        # stream_timeout=60s：超過就放棄（StreamRetryHandler 會 retry，最多 3 次）。
        # 同時把 stream_timeout 塞進 options，讓 stream_simple 的 _stream_once 也用它
        # 保護「消費階段」的 timeout（execute_stream_with_retry 只保護建立階段）。
        merged_opts.setdefault("stream_timeout", 60.0)
        response = await stream_simple_with_retry(
            model,
            ctx_dict,
            timeout_config=TimeoutConfig(stream_timeout=60.0),
            **merged_opts,
        )
        return {"events": response, "result": response.result}

    return _stream_fn


class AgentOptions:
    """Options for creating an Agent."""

    def __init__(
        self,
        *,
        initial_state: dict[str, Any] | None = None,
        convert_to_llm: Callable | None = None,
        transform_context: Callable | None = None,
        steering_mode: str = "one-at-a-time",
        follow_up_mode: str = "one-at-a-time",
        stream_fn: StreamFn | None = None,
        session_id: str | None = None,
        get_api_key: Callable | None = None,
        thinking_budgets: ThinkingBudgets | None = None,
        transport: Transport = "sse",
        max_retry_delay_ms: int | None = None,
    ):
        self.initial_state = initial_state or {}
        self.convert_to_llm = convert_to_llm
        self.transform_context = transform_context
        self.steering_mode = steering_mode
        self.follow_up_mode = follow_up_mode
        self.stream_fn = stream_fn
        self.session_id = session_id
        self.get_api_key = get_api_key
        self.thinking_budgets = thinking_budgets
        self.transport = transport
        self.max_retry_delay_ms = max_retry_delay_ms


class Agent:
    """
    Stateful agent with tool execution, event streaming, and message queuing.

    Mirrors the TypeScript Agent class from agent.ts.
    """

    def __init__(self, opts: AgentOptions | None = None):
        if opts is None:
            opts = AgentOptions()

        self._state = AgentState(
            system_prompt="",
            model=Model(api="", provider="", id=""),
            thinking_level="off",
            tools=[],
            messages=[],
            is_streaming=False,
            stream_message=None,
            pending_tool_calls=set(),
            error=None,
        )

        # Apply initial state overrides
        if opts.initial_state:
            for key, value in opts.initial_state.items():
                if hasattr(self._state, key):
                    setattr(self._state, key, value)

        self._listeners: set[Callable[[AgentEvent], None]] = set()
        self._cancel_event: asyncio.Event | None = None
        self._convert_to_llm = opts.convert_to_llm or _default_convert_to_llm
        self._transform_context = opts.transform_context
        self._steering_queue: deque[Message] = deque()
        self._follow_up_queue: deque[Message] = deque()
        self._steering_mode = opts.steering_mode
        self._follow_up_mode = opts.follow_up_mode
        # 如果 opts.stream_fn 是 None，用預設的 wrapper (wrap pi_ai.stream_simple)。
        # 這樣 agent 不會因為忘了傳 stream_fn 而靜默吞掉 ValueError 產生空內容。
        self.stream_fn: StreamFn = (
            opts.stream_fn if opts.stream_fn is not None else _get_default_stream_fn()
        )
        self._session_id = opts.session_id
        self.get_api_key = opts.get_api_key
        self._thinking_budgets = opts.thinking_budgets
        self._transport: Transport = opts.transport
        self._max_retry_delay_ms = opts.max_retry_delay_ms

        self._running_prompt: asyncio.Future[None] | None = None
        self._resolve_running_prompt: asyncio.Event | None = None

    # -- Properties --

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str | None) -> None:
        self._session_id = value

    @property
    def thinking_budgets(self) -> ThinkingBudgets | None:
        return self._thinking_budgets

    @thinking_budgets.setter
    def thinking_budgets(self, value: ThinkingBudgets | None) -> None:
        self._thinking_budgets = value

    @property
    def transport(self) -> Transport:
        return self._transport

    def set_transport(self, value: Transport) -> None:
        self._transport = value

    @property
    def max_retry_delay_ms(self) -> int | None:
        return self._max_retry_delay_ms

    @max_retry_delay_ms.setter
    def max_retry_delay_ms(self, value: int | None) -> None:
        self._max_retry_delay_ms = value

    # -- Subscription --

    def subscribe(self, fn: Callable[[AgentEvent], None]) -> Callable[[], None]:
        """Subscribe to agent events. Returns an unsubscribe callable."""
        self._listeners.add(fn)

        def unsubscribe() -> None:
            self._listeners.discard(fn)

        return unsubscribe

    # -- State mutators --

    def set_system_prompt(self, v: str) -> None:
        self._state.system_prompt = v

    def set_model(self, m: Model) -> None:
        self._state.model = m

    def set_thinking_level(self, level: ThinkingLevel) -> None:
        self._state.thinking_level = level

    def set_steering_mode(self, mode: str) -> None:
        self._steering_mode = mode

    def get_steering_mode(self) -> str:
        return self._steering_mode

    def set_follow_up_mode(self, mode: str) -> None:
        self._follow_up_mode = mode

    def get_follow_up_mode(self) -> str:
        return self._follow_up_mode

    def set_tools(self, tools: list[AgentTool]) -> None:
        self._state.tools = tools

    def replace_messages(self, messages: list[Message]) -> None:
        self._state.messages = list(messages)

    @staticmethod
    def _has_meaningful_content(partial: Message | None) -> bool:
        """Check if a partial message has non-empty content worth keeping."""
        if partial is None or partial.role != "assistant" or not partial.content:
            return False
        return any(
            (isinstance(c, ThinkingContent) and c.thinking.strip())
            or (isinstance(c, TextContent) and c.text.strip())
            or (isinstance(c, ToolCall) and c.name.strip())
            for c in partial.content
        )

    def append_message(self, message: Message) -> None:
        self._state.messages = [*self._state.messages, message]

    def clear_messages(self) -> None:
        self._state.messages = []

    # -- Queue management --

    def steer(self, message: Message) -> None:
        """Queue a steering message to interrupt the agent mid-run."""
        self._steering_queue.append(message)

    def follow_up(self, message: Message) -> None:
        """Queue a follow-up message to be processed after the agent finishes."""
        self._follow_up_queue.append(message)

    def clear_steering_queue(self) -> None:
        self._steering_queue.clear()

    def clear_follow_up_queue(self) -> None:
        self._follow_up_queue.clear()

    def clear_all_queues(self) -> None:
        self._steering_queue.clear()
        self._follow_up_queue.clear()

    def has_queued_messages(self) -> bool:
        return len(self._steering_queue) > 0 or len(self._follow_up_queue) > 0

    @staticmethod
    def _dequeue(queue: deque[Message], mode: str) -> list[Message]:
        if mode == "one-at-a-time":
            return [queue.popleft()] if queue else []
        out = list(queue)
        queue.clear()
        return out

    def _dequeue_steering_messages(self) -> list[Message]:
        return self._dequeue(self._steering_queue, self._steering_mode)

    def _dequeue_follow_up_messages(self) -> list[Message]:
        return self._dequeue(self._follow_up_queue, self._follow_up_mode)

    # -- Control methods --

    def abort(self) -> None:
        """Abort the current agent loop."""
        if self._cancel_event:
            self._cancel_event.set()

    async def wait_for_idle(self) -> None:
        """Wait for the agent to finish processing."""
        if self._resolve_running_prompt:
            await self._resolve_running_prompt.wait()

    def reset(self) -> None:
        """Reset agent state."""
        self._state.messages = []
        self._state.is_streaming = False
        self._state.stream_message = None
        self._state.pending_tool_calls = set()
        self._state.error = None
        self._steering_queue.clear()
        self._follow_up_queue.clear()

    # -- Prompt methods --

    async def prompt(
        self,
        input_: str | Message | list[Message],
        images: list[ImageContent] | None = None,
    ) -> None:
        """
        Send a prompt to the agent.

        Args:
            input_: A string, Message, or list of Messages.
            images: Optional images to attach (only when input_ is a string).
        """
        if self._state.is_streaming:
            raise RuntimeError(
                "Agent is already processing a prompt. Use steer() or follow_up() "
                "to queue messages, or wait for completion."
            )

        if not self._state.model.id:
            raise ValueError("No model configured")

        msgs: list[Message]

        if isinstance(input_, list):
            msgs = input_
        elif isinstance(input_, str):
            content: list[TextContent | ImageContent] = [TextContent(text=input_)]
            if images:
                content.extend(images)
            msgs = [UserMessage(content=content)]
        else:
            msgs = [input_]

        await self._run_loop(msgs)

    async def continue_(self) -> None:
        """
        Continue from current context (retries and resuming queued messages).
        Named continue_ to avoid Python keyword conflict.
        """
        if self._state.is_streaming:
            raise RuntimeError("Agent is already processing. Wait for completion before continuing.")

        messages = self._state.messages
        if not messages:
            raise ValueError("No messages to continue from")

        last_role = messages[-1].role if hasattr(messages[-1], "role") else messages[-1].get("role")
        if last_role == "assistant":
            queued_steering = self._dequeue_steering_messages()
            if queued_steering:
                await self._run_loop(queued_steering, skip_initial_steering_poll=True)
                return

            queued_follow_up = self._dequeue_follow_up_messages()
            if queued_follow_up:
                await self._run_loop(queued_follow_up)
                return

            raise ValueError("Cannot continue from message role: assistant")

        await self._run_loop(None)

    # -- Internal loop --

    async def _run_loop(
        self,
        messages: list[Message] | None = None,
        *,
        skip_initial_steering_poll: bool = False,
    ) -> None:
        """Run the agent loop."""
        model = self._state.model
        if not model.id:
            raise ValueError("No model configured")

        self._resolve_running_prompt = asyncio.Event()
        self._cancel_event = asyncio.Event()
        self._state.is_streaming = True
        self._state.stream_message = None
        self._state.error = None

        reasoning = None if self._state.thinking_level == "off" else self._state.thinking_level

        context = AgentContext(
            system_prompt=self._state.system_prompt,
            messages=list(self._state.messages),
            tools=list(self._state.tools),
        )

        _skip_initial = skip_initial_steering_poll

        async def get_steering() -> list[Message]:
            nonlocal _skip_initial
            if _skip_initial:
                _skip_initial = False
                return []
            return self._dequeue_steering_messages()

        async def get_follow_up() -> list[Message]:
            return self._dequeue_follow_up_messages()

        config = AgentLoopConfig(
            model=model,
            reasoning=reasoning,
            session_id=self._session_id,
            transport=self._transport,
            thinking_budgets=self._thinking_budgets,
            max_retry_delay_ms=self._max_retry_delay_ms,
            convert_to_llm=self._convert_to_llm,
            transform_context=self._transform_context,
            get_api_key=self.get_api_key,
            get_steering_messages=get_steering,
            get_follow_up_messages=get_follow_up,
        )

        partial: Message | None = None

        try:
            if messages is not None:
                stream = agent_loop(messages, context, config, self._cancel_event, self.stream_fn)
            else:
                stream = agent_loop_continue(context, config, self._cancel_event, self.stream_fn)

            async for event in stream:
                event_type = event.type if hasattr(event, "type") else None

                if event_type in ("message_start", "message_update"):
                    partial = event.message
                    self._state.stream_message = event.message

                elif event_type == "message_end":
                    partial = None
                    self._state.stream_message = None
                    self.append_message(event.message)

                elif event_type == "tool_execution_start":
                    self._state.pending_tool_calls = self._state.pending_tool_calls | {event.tool_call_id}

                elif event_type == "tool_execution_end":
                    self._state.pending_tool_calls = self._state.pending_tool_calls - {event.tool_call_id}

                elif event_type == "turn_end":
                    msg = event.message
                    if (
                        hasattr(msg, "role")
                        and msg.role == "assistant"
                        and hasattr(msg, "error_message")
                        and msg.error_message
                    ):
                        self._state.error = msg.error_message

                elif event_type == "agent_end":
                    self._state.is_streaming = False
                    self._state.stream_message = None

                self._emit(event)

            # Handle remaining partial message
            if self._has_meaningful_content(partial):
                self.append_message(partial)
            elif (
                partial is not None
                and partial.role == "assistant"
                and self._cancel_event
                and self._cancel_event.is_set()
            ):
                raise RuntimeError("Request was aborted")

        except Exception as err:
            error_msg = AssistantMessage(
                content=[TextContent(text="")],
                api=model.api,
                provider=model.provider,
                model=model.id,
                stop_reason="aborted" if (self._cancel_event and self._cancel_event.is_set()) else "error",
                error_message=str(err),
            )
            self.append_message(error_msg)
            self._state.error = str(err)
            self._emit(AgentEndEvent(messages=[error_msg]))

        finally:
            self._state.is_streaming = False
            self._state.stream_message = None
            self._state.pending_tool_calls = set()
            self._cancel_event = None
            if self._resolve_running_prompt:
                self._resolve_running_prompt.set()
            self._resolve_running_prompt = None

    def _emit(self, event: AgentEvent) -> None:
        """Emit an event to all subscribers."""
        for listener in self._listeners:
            listener(event)
