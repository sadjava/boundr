from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

_PROMPT_PATH = Path(__file__).with_name("judge_prompt.txt")
_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
_PROMPT_TAG = hashlib.sha1(_PROMPT.encode()).hexdigest()[:8]
_TIMEOUT = 120
_CHUNK = 8


@dataclass(frozen=True)
class JudgeQuery:
    kind: str
    pred: str
    gt: str


class Judge:
    def __init__(
        self,
        model: str,
        api_key: str | None,
        cache_path: Path,
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.cache_path = cache_path
        self.base_url = base_url.rstrip("/")
        self.mismatch_count = 0
        self._cache: dict[str, bool] = {}
        if cache_path.exists():
            try:
                loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = None
            self._cache = loaded if isinstance(loaded, dict) else {}

    @property
    def disabled(self) -> bool:
        return not self.api_key

    def _key(self, query: JudgeQuery) -> str:
        return f"{self.model}|{_PROMPT_TAG}|{query.kind}|{query.pred}|{query.gt}"

    def judge(self, queries: list[JudgeQuery]) -> list[bool]:
        if self.disabled:
            self.mismatch_count += len(queries)
            return [False] * len(queries)

        pending = [q for q in queries if self._key(q) not in self._cache]
        if pending:
            for query, verdict in zip(pending, self._ask(pending)):
                self._cache[self._key(query)] = verdict
        return [self._cache.get(self._key(q), False) for q in queries]

    def _ask(self, queries: list[JudgeQuery]) -> list[bool]:
        if len(queries) > _CHUNK:
            out: list[bool] = []
            for index in range(0, len(queries), _CHUNK):
                out.extend(self._ask(queries[index : index + _CHUNK]))
            return out
        verdicts = self._request(queries)
        if verdicts is None and len(queries) > 1:
            mid = len(queries) // 2
            return self._ask(queries[:mid]) + self._ask(queries[mid:])
        if verdicts is None:
            print(f"warning: judge dropped {queries[0].kind} "
                  f"{queries[0].pred!r}/{queries[0].gt!r}", file=sys.stderr)
            return [False]
        return verdicts

    def _request(self, queries: list[JudgeQuery]) -> list[bool] | None:
        payload = json.dumps(
            [{"kind": q.kind, "pred": q.pred, "gt": q.gt} for q in queries],
            ensure_ascii=False,
        )
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0,
                "messages": [{"role": "user", "content": _PROMPT + payload}],
            },
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        try:
            content = response.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return None
        try:
            parsed = json.loads(_strip_fence(content))
            verdicts = [item.get("match") is True for item in parsed]
        except (json.JSONDecodeError, AttributeError, TypeError):
            return None
        if len(verdicts) != len(queries):
            return None
        return verdicts

    def save_cache(self) -> None:
        if not self._cache:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _strip_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text.strip()
