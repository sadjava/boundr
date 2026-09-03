from __future__ import annotations

from pydantic import BaseModel, model_validator


def _mid(start: float, end: float) -> float:
    return (start + end) / 2


class AnnotationSegment(BaseModel):
    model_config = {"extra": "ignore"}

    id: str
    start: float
    end: float
    action: str = ""
    object: str | None = None
    keyframe: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def coerce_legacy(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if out.get("object") in (None, "") and out.get("objects"):
            first = out["objects"][0]
            if isinstance(first, dict):
                out["object"] = first.get("label") or None
        obj = out.get("object")
        if obj in ("", "none", "None"):
            out["object"] = None
        start = float(out.get("start") or 0)
        end = float(out.get("end") or 0)
        kf = out.get("keyframe")
        if kf in (None, ""):
            kf = _mid(start, end)
        lo, hi = (start, end) if start <= end else (end, start)
        out["keyframe"] = min(hi, max(lo, float(kf)))
        return out

    @model_validator(mode="after")
    def ordered(self) -> AnnotationSegment:
        if self.end < self.start:
            raise ValueError("end must be >= start")
        return self


if __name__ == "__main__":
    missing = AnnotationSegment(id="1", start=1, end=3, action="pour")
    assert missing.keyframe == 2.0
    clamped = AnnotationSegment(id="1", start=1, end=3, action="pour", keyframe=9)
    assert clamped.keyframe == 3.0
    empty = AnnotationSegment(id="2", start=0, end=0, action="")
    assert empty.keyframe == 0.0
    print("ok")
