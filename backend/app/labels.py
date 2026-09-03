from __future__ import annotations


DEFAULT_ACTION_TYPES = [
    "pour",
    "push",
    "put",
    "pick_up",
    "open",
    "close",
    "grab",
    "wipe",
    "stir",
]
DEFAULT_OBJECTS = ["cup", "bottle", "person", "cabinet", "counter"]


def clean_labels(items: list[str] | None, fallback: list[str] | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items or []:
        s = " ".join(str(raw).split())
        key = s.lower()
        if not s or key in seen:
            continue
        seen.add(key)
        out.append(s)
    if out:
        return out
    return list(fallback or [])


if __name__ == "__main__":
    assert clean_labels([" Pour ", "pour", "push"]) == ["Pour", "push"]
    assert clean_labels([]) == []
    assert clean_labels([], DEFAULT_ACTION_TYPES) == DEFAULT_ACTION_TYPES
    print("ok")
