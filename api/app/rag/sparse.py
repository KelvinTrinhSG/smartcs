"""BM25-style sparse vectors for Qdrant (IDF is applied server-side via Modifier.IDF).

Vietnamese words are multi-syllable ("bảo hành"), so syllable bigrams are indexed too.
Every token is also indexed without diacritics, because customers often type "bao hanh".
"""

import re
import unicodedata
import zlib
from collections import Counter

_WORD = re.compile(r"\w+")
K1 = 1.2


def strip_accents(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text.lower())
    out: list[str] = []
    for variant in {text, strip_accents(text)}:
        words = _WORD.findall(variant)
        out += words
        out += [f"{a}_{b}" for a, b in zip(words, words[1:], strict=False)]
    return out


def _index(token: str) -> int:
    return zlib.crc32(token.encode("utf-8"))


def doc_vector(text: str) -> tuple[list[int], list[float]]:
    counts = Counter(_index(t) for t in tokens(text))
    indices = sorted(counts)
    # BM25 term-frequency saturation (no length normalisation: chunks are similar in size).
    return indices, [counts[i] * (K1 + 1) / (counts[i] + K1) for i in indices]


def query_vector(text: str) -> tuple[list[int], list[float]]:
    indices = sorted({_index(t) for t in tokens(text)})
    return indices, [1.0] * len(indices)
