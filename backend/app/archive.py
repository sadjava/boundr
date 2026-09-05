from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}
ANN_EXTS = {".json", ".csv"}


def _norm(name: str) -> str:
    return name.replace("\\", "/").strip("/")


def _skip(name: str) -> bool:
    n = _norm(name).lower()
    if not n or n.endswith("/"):
        return True
    if n.startswith("__macosx/") or "/__macosx/" in n:
        return True
    base = n.rsplit("/", 1)[-1]
    return base.startswith(".") or base == "thumbs.db"


def _in_folder(name: str, folder: str) -> bool:
    parts = [p.lower() for p in _norm(name).split("/")]
    return folder in parts[:-1]


def _video_files(names: list[str], folder: str | None) -> list[str]:
    out = []
    for name in names:
        if _skip(name):
            continue
        if Path(name).suffix.lower() not in VIDEO_EXTS:
            continue
        if folder and not _in_folder(name, folder):
            continue
        out.append(name)
    return out


def list_pairs(
    zf: ZipFile, with_annotations: bool
) -> list[tuple[str, str, dict[str, str] | None]]:
    """(display_name, video_member, {'.json'|'.csv': member} or None)."""
    names = zf.namelist()
    if not with_annotations:
        videos = _video_files(names, None)
        if not videos:
            raise ValueError("archive has no video files")
        return [(Path(n).name, n, None) for n in videos]

    videos = _video_files(names, "videos")
    anns = [
        n
        for n in names
        if not _skip(n) and _in_folder(n, "annotations") and Path(n).suffix.lower() in ANN_EXTS
    ]
    if not videos:
        raise ValueError("archive needs a videos/ folder with video files")
    if not anns:
        raise ValueError("archive needs an annotations/ folder with JSON or CSV files")

    vmap: dict[str, str] = {}
    amap: dict[str, dict[str, str]] = {}
    for name in videos:
        stem = Path(name).stem.lower()
        if stem in vmap:
            raise ValueError(f"duplicate video name: {Path(name).name}")
        vmap[stem] = name
    for name in anns:
        stem = Path(name).stem.lower()
        ext = Path(name).suffix.lower()
        bucket = amap.setdefault(stem, {})
        if ext in bucket:
            raise ValueError(f"duplicate annotation: {Path(name).name}")
        bucket[ext] = name
    if set(vmap) != set(amap):
        raise ValueError("videos/ and annotations/ must have the same filenames")
    return [(Path(vmap[stem]).name, vmap[stem], amap[stem]) for stem in sorted(vmap)]


if __name__ == "__main__":
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("videos/clip.mp4", b"x")
        z.writestr("annotations/clip.json", b"{}")
        z.writestr("__MACOSX/videos/._clip.mp4", b"junk")
    pairs = list_pairs(zipfile.ZipFile(io.BytesIO(buf.getvalue())), True)
    assert pairs == [("clip.mp4", "videos/clip.mp4", {".json": "annotations/clip.json"})], pairs

    both = io.BytesIO()
    with zipfile.ZipFile(both, "w") as z:
        z.writestr("videos/clip.mp4", b"x")
        z.writestr("annotations/clip.json", b"{}")
        z.writestr("annotations/clip.csv", b"h")
    pairs2 = list_pairs(zipfile.ZipFile(io.BytesIO(both.getvalue())), True)
    assert pairs2[0][2] == {
        ".json": "annotations/clip.json",
        ".csv": "annotations/clip.csv",
    }

    bare = io.BytesIO()
    with zipfile.ZipFile(bare, "w") as z:
        z.writestr("nested/a.mp4", b"x")
        z.writestr("readme.txt", b"no")
    assert list_pairs(zipfile.ZipFile(io.BytesIO(bare.getvalue())), False) == [
        ("a.mp4", "nested/a.mp4", None)
    ]
    print("ok")
