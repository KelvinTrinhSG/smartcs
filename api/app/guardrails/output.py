"""Output guard: block answers that leak the system prompt or internal tool names."""

CANARY = "SCS-7F3A-CANARY"

# Strings that only appear in our prompts / tool specs. One canary hit or two markers = leak.
MARKERS = ("search_kb", "lookup_order", "create_ticket", "book_appointment", "handoff_to_human",
           "<document", "Quy tắc:", "needs_handoff", "phone_not_verified", "AGENT_RULES")


def leaks_prompt(answer: str) -> bool:
    if CANARY.lower() in answer.lower():
        return True
    return sum(m.lower() in answer.lower() for m in MARKERS) >= 2
