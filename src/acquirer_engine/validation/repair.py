"""Return precise validation feedback in a protocol-valid conversation.

Owns: Closing pending output calls with errors while retaining the failed draft.
Does not own: Retry limits, model selection, or relaxing validation rules.
"""

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
)


def repair_history(messages: list[ModelMessage], errors: list[str]) -> list[ModelMessage] | None:
    """Attach errors to the rejected output without discarding its evidence history.

    Args:
        messages: Captured conversation from the failed agent run.
        errors: Specific schema or evidence validation errors.
    Returns:
        A complete conversation, or None when no draft can be repaired.
    """
    if messages and isinstance(messages[-1], ModelRequest) and not messages[-1].parts:
        messages = messages[:-1]
    if not messages or not isinstance(messages[-1], ModelResponse):
        return None
    pending = [part for part in messages[-1].parts if isinstance(part, ToolCallPart)]
    if not pending:
        return None
    return [
        *messages,
        ModelRequest(
            parts=[
                RetryPromptPart(
                    content="\n".join(errors),
                    tool_name=part.tool_name,
                    tool_call_id=part.tool_call_id,
                )
                for part in pending
            ]
        ),
    ]
