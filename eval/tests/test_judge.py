from __future__ import annotations

import json
from pathlib import Path

from evallib.judge import Judge, JudgeQuery


class FakePost:
    """Подменяет requests.post и считает вызовы."""

    def __init__(self, matches: list[bool]) -> None:
        self.matches = matches
        self.calls = 0

    def __call__(self, url: str, **kwargs: object) -> "FakePost":
        self.calls += 1
        return self

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        content = json.dumps([{"match": m, "reason": "test"} for m in self.matches])
        return {"choices": [{"message": {"content": content}}]}


def test_disabled_without_api_key(tmp_path: Path) -> None:
    judge = Judge("model", None, tmp_path / "cache.json")
    assert judge.disabled is True
    assert judge.judge([JudgeQuery("action", "grab", "take")]) == [False]
    assert judge.mismatch_count == 1


def test_calls_api_and_returns_verdicts(tmp_path: Path, monkeypatch) -> None:
    fake = FakePost([True, False])
    monkeypatch.setattr("evallib.judge.requests.post", fake)
    judge = Judge("model", "key", tmp_path / "cache.json")
    verdicts = judge.judge([
        JudgeQuery("action", "grab", "take"),
        JudgeQuery("object", "cup", "plate"),
    ])
    assert verdicts == [True, False]
    assert fake.calls == 1


def test_second_call_uses_cache(tmp_path: Path, monkeypatch) -> None:
    fake = FakePost([True])
    monkeypatch.setattr("evallib.judge.requests.post", fake)
    judge = Judge("model", "key", tmp_path / "cache.json")
    query = JudgeQuery("action", "grab", "take")
    assert judge.judge([query]) == [True]
    assert judge.judge([query]) == [True]
    assert fake.calls == 1


def test_cache_survives_restart(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "cache.json"
    fake = FakePost([True])
    monkeypatch.setattr("evallib.judge.requests.post", fake)
    first = Judge("model", "key", cache)
    first.judge([JudgeQuery("action", "grab", "take")])
    first.save_cache()

    second = Judge("model", "key", cache)
    assert second.judge([JudgeQuery("action", "grab", "take")]) == [True]
    assert fake.calls == 1


def test_malformed_response_counts_as_mismatch(tmp_path: Path, monkeypatch) -> None:
    class Broken(FakePost):
        def json(self) -> dict:
            return {"choices": [{"message": {"content": "не json"}}]}

    monkeypatch.setattr("evallib.judge.requests.post", Broken([]))
    judge = Judge("model", "key", tmp_path / "cache.json")
    assert judge.judge([JudgeQuery("action", "grab", "take")]) == [False]


def test_wrong_length_reply_is_retried_in_halves(tmp_path: Path, monkeypatch) -> None:
    class Flaky(FakePost):
        def __init__(self) -> None:
            super().__init__([])
            self.sizes: list[int] = []

        def __call__(self, url: str, **kwargs: object) -> "Flaky":
            body = kwargs["json"]["messages"][0]["content"]  # type: ignore[index]
            payload = json.loads(str(body)[str(body).rfind("["):])
            self.sizes.append(len(payload))
            self.matches = [True] if len(payload) > 2 else [True] * len(payload)
            return super().__call__(url, **kwargs)

    fake = Flaky()
    monkeypatch.setattr("evallib.judge.requests.post", fake)
    judge = Judge("model", "key", tmp_path / "cache.json")
    queries = [JudgeQuery("action", f"a{i}", f"b{i}") for i in range(4)]
    assert judge.judge(queries) == [True, True, True, True]
    assert fake.sizes[0] == 4
    assert fake.calls == 3


def test_missing_choices_does_not_crash(tmp_path: Path, monkeypatch) -> None:
    class NoChoices(FakePost):
        def json(self) -> dict:
            return {"error": {"message": "model unavailable"}}

    monkeypatch.setattr("evallib.judge.requests.post", NoChoices([]))
    judge = Judge("model", "key", tmp_path / "cache.json")
    assert judge.judge([JudgeQuery("action", "open", "open")]) == [False]


def test_empty_query_list_makes_no_call(tmp_path: Path, monkeypatch) -> None:
    fake = FakePost([])
    monkeypatch.setattr("evallib.judge.requests.post", fake)
    judge = Judge("model", "key", tmp_path / "cache.json")
    assert judge.judge([]) == []
    assert fake.calls == 0
