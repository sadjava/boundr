from __future__ import annotations

import re

_ARTICLES = {"a", "an", "the"}
_EMPTY = {"", "none", "null", "n/a", "-"}
_SUFFIXES = ("ing", "ed", "s")


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        # Порог длины оставляет короткие слова ("is", "cut") нетронутыми.
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def normalize(label: str | None) -> str:
    if label is None:
        return ""
    text = re.sub(r"[-_/]+", " ", str(label).strip().lower())
    text = re.sub(r"[^a-zа-яё0-9 ]+", "", text)
    words = [w for w in text.split() if w and w not in _ARTICLES]
    # Стеммим только одиночные слова: в составных метках ("cutting board")
    # отсечение окончания ломает устойчивое существительное.
    if len(words) == 1:
        words = [_stem(w) for w in words]
    result = " ".join(words)
    return "" if result in _EMPTY else result


def labels_equal(pred: str | None, gt: str | None) -> bool:
    return normalize(pred) == normalize(gt)
