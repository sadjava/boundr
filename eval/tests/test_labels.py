from __future__ import annotations

import pytest

from evallib.labels import labels_equal, normalize


@pytest.mark.parametrize("raw,expected", [
    ("Open", "open"),
    ("  OPENING  ", "open"),
    ("opened", "open"),
    ("cutting-board", "cutting board"),
    ("the drawer", "drawer"),
    ("a knife", "knife"),
    ("knives", "knive"),
    ("", ""),
    (None, ""),
])
def test_normalize(raw: str | None, expected: str) -> None:
    assert normalize(raw) == expected


def test_none_placeholder_is_empty() -> None:
    assert normalize("none") == ""


def test_short_words_keep_their_ending() -> None:
    # Отсечение окончаний не должно съедать короткие слова целиком.
    assert normalize("is") == "is"


def test_labels_equal_after_normalization() -> None:
    assert labels_equal("Opening", "open") is True
    assert labels_equal("grab", "take") is False


def test_empty_labels_are_equal() -> None:
    assert labels_equal("", None) is True
