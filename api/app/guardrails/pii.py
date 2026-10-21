"""Regex PII masking tuned for Vietnamese customer messages.

Applied to: the user message before it reaches the LLM, everything stored in `messages`, and the final
answer. The agent never needs a phone typed in chat (identity comes from Telegram verification), so masking
input loses nothing. Presidio would add NER for names/addresses, but pulls in spaCy models; regex covers
the high-risk identifiers here and is measured in evals/run_pii.py.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# 13-19 digits, optionally grouped by spaces/dashes; validated with Luhn below.
CARD = re.compile(r"(?<![\d])(?:\d[ -]?){12,18}\d(?![\d])")
# Mobile: 0 or +84/84 followed by 3/5/7/8/9 and 8 digits, separators allowed.
PHONE = re.compile(r"(?<![\d+])(?:\+?84|0)[\s.-]?[35789](?:[\s.-]?\d){8}(?![\d])")
# CCCD: 12 digits starting with a 0xx province code.
CCCD = re.compile(r"(?<!\d)0\d{11}(?!\d)")
# CMND (9 digits) and bank accounts only when a keyword is nearby: bare 9-16 digit runs are too ambiguous.
CMND_CTX = re.compile(r"(?i)(cmnd|chứng minh|cmt)[^\d]{0,20}(\d{9})(?!\d)")
BANK_CTX = re.compile(r"(?i)(stk|số tài khoản|so tai khoan|tài khoản số|account)[^\d]{0,20}(\d{8,16})(?!\d)")
CVV_CTX = re.compile(r"(?i)(cvv|cvc|mã bảo mật)[^\d]{0,10}(\d{3,4})(?!\d)")

LABELS = {"EMAIL": "[EMAIL]", "CARD": "[SỐ_THẺ]", "PHONE": "[SĐT]", "CCCD": "[CCCD]", "CMND": "[CMND]",
          "BANK": "[STK]", "CVV": "[CVV]"}


def _luhn(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@dataclass
class MaskResult:
    text: str
    found: Counter = field(default_factory=Counter)

    @property
    def changed(self) -> bool:
        return bool(self.found)


def mask(text: str) -> MaskResult:
    found: Counter = Counter()

    def sub(kind: str, pattern: re.Pattern, s: str, check=None, group: int = 0) -> str:
        def repl(m: re.Match) -> str:
            value = m.group(group)
            if check and not check(value):
                return m.group(0)
            found[kind] += 1
            if group == 0:
                return LABELS[kind]
            start, end = m.span(group)
            return m.group(0)[: start - m.start()] + LABELS[kind] + m.group(0)[end - m.start():]

        return pattern.sub(repl, s)

    s = sub("EMAIL", EMAIL, text)
    s = sub("CARD", CARD, s, check=lambda v: _luhn(re.sub(r"\D", "", v)))
    s = sub("CVV", CVV_CTX, s, group=2)
    s = sub("CMND", CMND_CTX, s, group=2)
    s = sub("BANK", BANK_CTX, s, group=2)
    s = sub("CCCD", CCCD, s)
    s = sub("PHONE", PHONE, s)
    return MaskResult(s, found)
