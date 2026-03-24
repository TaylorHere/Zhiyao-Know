from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from src.agents.common import load_chat_model
from src.agents.common.tools import get_kb_based_tools, get_buildin_tools
from src.services.mcp_service import get_enabled_mcp_tools
from src.utils.logging_config import logger

CHINESE_OUTPUT_GUARD_PROMPT = (
    "【语言约束】你必须全程使用简体中文输出，包括推理内容与最终答复。"
    "除非用户明确要求英文或翻译任务，否则禁止输出英文句子。"
    "若必须出现英文缩写或术语（如 API、SQL、HTTP、ID），请先写中文，再在括号内补充英文。"
)


def _is_system_like_role(role: Any) -> bool:
    if role is None:
        return False
    role_text = str(role).strip().lower()
    return role_text in {"system", "developer"}


def _is_system_message(msg: Any) -> bool:
    if isinstance(msg, dict):
        role = msg.get("role") or msg.get("type")
        return _is_system_like_role(role)
    if isinstance(msg, (tuple, list)) and len(msg) >= 1:
        return _is_system_like_role(msg[0])
    msg_type = getattr(msg, "type", None) or getattr(msg, "role", None)
    if _is_system_like_role(msg_type):
        return True
    # Fallback for message classes that don't expose role/type directly.
    class_name = msg.__class__.__name__.lower()
    if "system" in class_name or "developer" in class_name:
        return True
    # Some wrappers store role in extra/additional kwargs.
    additional_kwargs = getattr(msg, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict) and _is_system_like_role(additional_kwargs.get("role")):
        return True
    extra = getattr(msg, "extra", None)
    if isinstance(extra, dict) and _is_system_like_role(extra.get("role")):
        return True
    return False


def _is_user_message(msg: Any) -> bool:
    if isinstance(msg, dict):
        role = msg.get("role") or msg.get("type")
        return role in {"user", "human"}
    msg_type = getattr(msg, "type", None) or getattr(msg, "role", None)
    return msg_type in {"user", "human"}


def _get_message_content(msg: Any) -> str | None:
    if isinstance(msg, dict):
        content = msg.get("content")
        return str(content) if content is not None else None
    if isinstance(msg, (tuple, list)) and len(msg) >= 2:
        content = msg[1]
        return str(content) if content is not None else None
    content = getattr(msg, "content", None)
    return str(content) if content is not None else None


def _has_language_guard_prompt(msg: Any) -> bool:
    content = _get_message_content(msg)
    return isinstance(content, str) and "【语言约束】" in content


def _partition_messages_system_first(messages: list[Any]) -> tuple[list[Any], list[Any]]:
    systems: list[Any] = []
    remaining: list[Any] = []
    for msg in messages:
        if _is_system_message(msg):
            systems.append(msg)
        else:
            remaining.append(msg)
    return systems, remaining


def _message_role_label(msg: Any) -> str:
    if isinstance(msg, dict):
        role = msg.get("role") or msg.get("type")
        if role is not None:
            return str(role)
    if isinstance(msg, (tuple, list)) and len(msg) >= 1:
        return str(msg[0])
    role = getattr(msg, "role", None) or getattr(msg, "type", None)
    if role is not None:
        return str(role)
    additional_kwargs = getattr(msg, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict) and additional_kwargs.get("role") is not None:
        return str(additional_kwargs.get("role"))
    return msg.__class__.__name__


def _system_out_of_prefix_positions(messages: list[Any]) -> list[int]:
    positions: list[int] = []
    seen_non_system = False
    for idx, msg in enumerate(messages):
        if _is_system_message(msg):
            if seen_non_system:
                positions.append(idx)
        else:
            seen_non_system = True
    return positions


def _safe_preview(text: str | None, limit: int = 300) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").replace("\r", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"


def _safe_repr(obj: Any, limit: int = 1200) -> str:
    try:
        return _safe_preview(repr(obj), limit=limit)
    except Exception:
        return f"<unreprable:{obj.__class__.__name__}>"


def _message_snapshot(msg: Any) -> dict[str, Any]:
    if isinstance(msg, dict):
        role = msg.get("role") or msg.get("type")
        content = _safe_preview(str(msg.get("content", "")))
        return {"role": role, "content_preview": content}
    role = getattr(msg, "type", None) or getattr(msg, "role", None) or msg.__class__.__name__
    content = _safe_preview(_get_message_content(msg))
    return {"role": role, "content_preview": content}


def _extract_llm_error_snapshot(e: Exception) -> dict[str, Any]:
    response = getattr(e, "response", None)
    response_text = None
    if response is not None:
        text_attr = getattr(response, "text", None)
        if isinstance(text_attr, str):
            response_text = text_attr
        elif callable(text_attr):
            try:
                response_text = text_attr()
            except Exception:
                response_text = None

    return {
        "error_type": e.__class__.__name__,
        "error_message": str(e),
        "status_code": getattr(e, "status_code", None),
        "error_body": _safe_repr(getattr(e, "body", None)),
        "error_response_text": _safe_preview(response_text, limit=2000) if response_text else None,
        "error_response_repr": _safe_repr(response, limit=2000) if response is not None else None,
    }


def _get_token_encoder():
    try:
        import tiktoken

        try:
            return tiktoken.get_encoding("o200k_base")
        except Exception:
            return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


_TOKEN_ENCODER = _get_token_encoder()


def _estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    if _TOKEN_ENCODER is not None:
        try:
            return len(_TOKEN_ENCODER.encode(text, disallowed_special=()))
        except Exception:
            pass
    # Fallback: 粗略估算，避免 tokenizer 不可用时失去保护
    return max(1, len(text) // 4)


def _message_to_token_text(msg: Any) -> str:
    if isinstance(msg, dict):
        role = msg.get("role") or msg.get("type") or "unknown"
        content = msg.get("content", "")
    else:
        role = getattr(msg, "role", None) or getattr(msg, "type", None) or "unknown"
        content = getattr(msg, "content", "")

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type == "text":
                    parts.append(str(item.get("text", "")))
                elif item_type == "image_url":
                    parts.append("[image]")
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        content_text = "\n".join(parts)
    elif isinstance(content, dict):
        content_text = json.dumps(content, ensure_ascii=False)
    else:
        content_text = str(content)

    return f"{role}: {content_text}\n"


def _estimate_messages_tokens(messages: list[Any]) -> int:
    return sum(_estimate_text_tokens(_message_to_token_text(msg)) for msg in messages)


def _get_input_token_budget() -> int:
    context_window = int(os.getenv("YUXI_CHAT_CONTEXT_WINDOW", "16384"))
    input_ratio = float(os.getenv("YUXI_CHAT_INPUT_TOKEN_RATIO", "0.9"))
    output_reserve = int(os.getenv("YUXI_CHAT_OUTPUT_TOKEN_RESERVE", "1024"))
    ratio_budget = int(context_window * input_ratio)
    reserve_budget = context_window - output_reserve
    budget = min(ratio_budget, reserve_budget)
    return max(512, budget)


def _is_context_length_error(e: Exception) -> bool:
    text = str(e).lower()
    return (
        "context length" in text
        or "input_tokens" in text
        or "maximum input length" in text
        or "max context length" in text
    )


def _trim_oldest_non_system_messages(messages: list[Any], drop_count: int) -> list[Any]:
    systems: list[Any] = []
    non_systems: list[Any] = []
    for msg in messages:
        if _is_system_message(msg):
            systems.append(msg)
        else:
            non_systems.append(msg)

    # 必须保留最新 user/human 消息，避免下游模型报 "No user query found in messages"
    last_user_idx = -1
    for i in range(len(non_systems) - 1, -1, -1):
        if _is_user_message(non_systems[i]):
            last_user_idx = i
            break

    # 没有 user/human 的请求，不做裁剪（例如某些工具链内部阶段）
    if last_user_idx < 0:
        return messages

    # 至少保留：最新 user/human + 其后一条消息（如果存在）
    min_keep_non_system = max(1, len(non_systems) - last_user_idx)
    if len(non_systems) <= min_keep_non_system:
        return messages

    keep_non_system = max(min_keep_non_system, len(non_systems) - drop_count)
    trimmed_non_systems = non_systems[-keep_non_system:]
    return [*systems, *trimmed_non_systems]


def _trim_messages_to_token_budget(messages: list[Any], budget: int) -> tuple[list[Any], int]:
    current = list(messages)
    # 没有 user/human 时不做前置裁剪，避免破坏工具链内部调用
    if not any(_is_user_message(msg) for msg in current):
        return current, _estimate_messages_tokens(current)

    estimated = _estimate_messages_tokens(current)
    if estimated <= budget:
        return current, estimated

    # 分批删除最旧历史消息，避免逐条删除造成多次重复估算
    drop_steps = [4, 8, 12, 16, 24, 32]
    for drop_count in drop_steps:
        trimmed = _trim_oldest_non_system_messages(current, drop_count=drop_count)
        if len(trimmed) >= len(current):
            break
        current = trimmed
        estimated = _estimate_messages_tokens(current)
        if estimated <= budget:
            return current, estimated

    # 仍超限时，继续强制每次删 1 条，直到达到预算或触达最小保留
    while estimated > budget:
        trimmed = _trim_oldest_non_system_messages(current, drop_count=1)
        if len(trimmed) >= len(current):
            break
        current = trimmed
        estimated = _estimate_messages_tokens(current)

    return current, estimated


class RuntimeConfigMiddleware(AgentMiddleware):
    """运行时配置中间件 - 应用模型/工具/知识库/MCP/提示词配置

    注意：所有可能用到的知识库工具必须在初始化时预加载并注册到 self.tools
    运行时根据配置从 self.tools 中筛选工具，不能动态添加新工具
    """

    def __init__(self, *, extra_tools: list[Any] | None = None):
        """初始化中间件

        Args:
            extra_tools: 额外工具列表（从 create_agent 的 tools 参数传入）
        """
        super().__init__()
        # 这里的工具只是提供给 langchain 调用，并不是真正的绑定在模型上
        self.kb_tools = get_kb_based_tools()
        self.buildin_tools = get_buildin_tools()
        self.tools = self.kb_tools + self.buildin_tools + (extra_tools or [])
        logger.debug(f"Initialized tools: {len(self.tools)}")

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        runtime_context = request.runtime.context

        model = load_chat_model(getattr(runtime_context, "model", None))
        enabled_tools = await self.get_tools_from_context(runtime_context)
        logger.debug(f"RuntimeConfigMiddleware: model={model}, "
                     f"tools={[t.name for t in enabled_tools]}. ")

        # vLLM/HF chat template requires every system message to be at the beginning.
        # Partition messages globally so no system message remains in the middle/tail.
        existing_systems, remaining = _partition_messages_system_first(list(request.messages))

        # Keep create_agent(system_prompt=...) as the single source of system prompt.
        # Runtime middleware only normalizes ordering for vLLM compatibility.
        has_language_guard = any(_has_language_guard_prompt(msg) for msg in existing_systems)
        if not has_language_guard:
            existing_systems.append({"role": "system", "content": CHINESE_OUTPUT_GUARD_PROMPT})

        messages = [*existing_systems, *remaining]
        # Final safeguard: re-partition once more to tolerate unrecognized message wrappers.
        systems2, remaining2 = _partition_messages_system_first(messages)
        messages = [*systems2, *remaining2]
        out_of_prefix_positions = _system_out_of_prefix_positions(messages)
        if out_of_prefix_positions:
            logger.warning(
                "Detected non-prefix system/developer messages before model call, "
                f"positions={out_of_prefix_positions}. Forcing reorder again."
            )
            s3, r3 = _partition_messages_system_first(messages)
            messages = [*s3, *r3]

        # 前置裁剪：调用模型前先按 token 预算裁剪最旧历史消息，减少超限重试。
        token_budget = _get_input_token_budget()
        estimated_tokens_before = _estimate_messages_tokens(messages)
        trimmed_messages, estimated_tokens_after = _trim_messages_to_token_budget(messages, token_budget)
        if len(trimmed_messages) < len(messages):
            logger.warning(
                "Pre-trimmed chat history before model call: "
                f"messages {len(messages)} -> {len(trimmed_messages)}, "
                f"tokens_est {estimated_tokens_before} -> {estimated_tokens_after}, "
                f"budget={token_budget}"
            )
        messages = trimmed_messages

        request = request.override(model=model, tools=enabled_tools, messages=messages)

        # Build debug snapshot once, and emit it only when model call fails.
        model_name = getattr(model, "model_name", None) or getattr(model, "model", None)
        model_identifier = getattr(model, "model_identifier", None)
        model_base_url = (
            getattr(model, "openai_api_base", None)
            or getattr(model, "base_url", None)
            or getattr(model, "api_base", None)
        )
        model_kwargs = getattr(model, "model_kwargs", None) or {}
        debug_snapshot = {
            "runtime_model_spec": getattr(runtime_context, "model", None),
            "resolved_model_name": model_name,
            "resolved_model_identifier": model_identifier,
            "resolved_model_base_url": model_base_url,
            "resolved_model_kwargs": model_kwargs,
            "tool_names": [t.name for t in enabled_tools],
            "tool_count": len(enabled_tools),
            "message_count": len(messages),
            "estimated_tokens": estimated_tokens_after,
            "token_budget": token_budget,
            "messages_preview": [_message_snapshot(m) for m in messages[:6]],
            "message_roles": [f"{idx}:{_message_role_label(m)}" for idx, m in enumerate(messages[:80])],
            "system_out_of_prefix_positions": _system_out_of_prefix_positions(messages),
        }

        # Keep request snapshot for troubleshooting, but avoid high-volume warning logs in production.
        logger.debug(f"RuntimeConfigMiddleware model call request: {debug_snapshot}")

        current_request = request
        current_messages = list(messages)

        # 上下文超长时，逐步裁剪最旧历史消息并重试，避免长对话直接 400 失败。
        trim_drop_steps = [4, 8, 12]

        for attempt in range(len(trim_drop_steps) + 1):
            try:
                response = await handler(current_request)
                # Do not log full response payload; large model outputs can flood logs and block streaming.
                logger.debug(
                    "RuntimeConfigMiddleware model call response: "
                    f"{{'response_type': '{type(response).__name__}'}}"
                )
                return response
            except Exception as e:
                error_snapshot = _extract_llm_error_snapshot(e)
                logger.error(
                    f"RuntimeConfigMiddleware model call failed: {type(e).__name__}: {e}\n"
                    f"Request snapshot: {debug_snapshot}\n"
                    f"LLM error snapshot: {error_snapshot}"
                )

                if attempt >= len(trim_drop_steps) or not _is_context_length_error(e):
                    raise

                drop_count = trim_drop_steps[attempt]
                trimmed_messages = _trim_oldest_non_system_messages(current_messages, drop_count=drop_count)
                if len(trimmed_messages) >= len(current_messages):
                    raise

                logger.warning(
                    "Detected context-length overflow, retrying with trimmed history: "
                    f"attempt={attempt + 1}, original_messages={len(current_messages)}, "
                    f"trimmed_messages={len(trimmed_messages)}, drop_count={drop_count}"
                )

                current_messages = trimmed_messages
                current_request = current_request.override(messages=current_messages)

    async def get_tools_from_context(self, context) -> list:
        """从上下文配置中获取工具列表"""
        # 1. 基础工具 (从 context.tools 中筛选)
        selected_tools = []

        if context.tools:
            # 创建工具映射表
            tools_map = {t.name: t for t in self.tools}
            for tool_name in context.tools:
                if tool_name in tools_map:
                    selected_tools.append(tools_map[tool_name])
                else:
                    logger.warning(f"Tool '{tool_name}' not found in available tools. {tools_map.keys()=}")

        # 2. 知识库工具
        if context.knowledges:
            kb_tools = get_kb_based_tools(db_names=context.knowledges)
            selected_tools.extend(kb_tools)

        # 3. MCP 工具（使用统一入口，自动过滤 disabled_tools）
        if context.mcps:
            for server_name in context.mcps:
                mcp_tools = await get_enabled_mcp_tools(server_name)
                selected_tools.extend(mcp_tools)

        return selected_tools
