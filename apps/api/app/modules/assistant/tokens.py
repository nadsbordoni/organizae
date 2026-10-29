import math

from app.modules.assistant.providers.base import ContextMessage


def estimate_text_tokens(text: str) -> int:
    """Heuristic for bounded candidate retrieval, not API consumption."""
    return max(1, math.ceil(len(text.encode("utf-8")) / 4))


def history_candidates(
    messages: list[ContextMessage], budget: int
) -> list[ContextMessage]:
    """Keep a recent suffix of whole turns with a margin for SDK token counting."""
    result: list[ContextMessage] = []
    estimate = 0
    for index in range(len(messages) - 2, -1, -2):
        turn = messages[index : index + 2]
        cost = sum(estimate_text_tokens(item.content) + 8 for item in turn)
        if result and estimate + cost > budget * 2:
            break
        result[0:0] = turn
        estimate += cost
    return result
