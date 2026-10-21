"""Text clean-up for answers that will be read aloud by TTS."""

import re

DIGITS = ("không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín")
LETTERS = {"T": "tê", "Z": "dét"}
CODE_RE = re.compile(r"\bTZ\d{3,}\b", re.IGNORECASE)


def _spell(code: str) -> str:
    return " ".join(LETTERS.get(c, DIGITS[int(c)] if c.isdigit() else c) for c in code.upper())


def speakable(text: str) -> str:
    """Spell order codes character by character: TTS reads "TZ20002" as a number, and the model
    miscounts zeros when asked to spell them itself."""
    return CODE_RE.sub(lambda m: _spell(m.group(0)), text)
