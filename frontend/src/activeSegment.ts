import type { AnnotationSegment } from "./types";

/** Covering hit with the latest start. Half-open [start, end) so nested inner yields back to outer at inner.end. */
export function activeSegmentId(
  t: number,
  segments: AnnotationSegment[],
  current: string | null,
): string | null {
  const hits = segments.filter((s) => t >= s.start && t < s.end);
  if (!hits.length) return current;
  return hits.reduce((best, s) => (s.start > best.start ? s : best)).id;
}

export function playheadInside(seg: AnnotationSegment, t: number): boolean {
  return t > seg.start && t < seg.end;
}

function clampKf(start: number, end: number, kf: number): number {
  return Math.min(end, Math.max(start, kf));
}

/** Duplicate `id` directly below itself; top ends at `t`, copy starts at `t`. */
export function splitSegmentAt(
  segments: AnnotationSegment[],
  id: string,
  t: number,
  newId: () => string = () => crypto.randomUUID(),
): AnnotationSegment[] | null {
  const i = segments.findIndex((s) => s.id === id);
  if (i < 0) return null;
  const seg = segments[i];
  if (!playheadInside(seg, t)) return null;
  const top: AnnotationSegment = { ...seg, end: t, keyframe: clampKf(seg.start, t, seg.keyframe) };
  const bottom: AnnotationSegment = {
    ...seg,
    id: newId(),
    start: t,
    keyframe: clampKf(t, seg.end, seg.keyframe),
  };
  const next = segments.slice();
  next.splice(i, 1, top, bottom);
  return next;
}

export function checkActiveSegment() {
  const segs: AnnotationSegment[] = [
    { id: "1", start: 0, end: 10, action: "a", object: null, keyframe: 5 },
    { id: "2", start: 3, end: 6, action: "b", object: null, keyframe: 4.5 },
  ];
  if (activeSegmentId(1, segs, null) !== "1") throw new Error("outer before inner");
  if (activeSegmentId(3, segs, "1") !== "2") throw new Error("switch when inner starts");
  if (activeSegmentId(4, segs, "1") !== "2") throw new Error("stay on latest started");
  if (activeSegmentId(6, segs, "2") !== "1") throw new Error("back to outer when inner ends");
  const overlap: AnnotationSegment[] = [
    { id: "a", start: 0, end: 5, action: "a", object: null, keyframe: 2.5 },
    { id: "b", start: 2, end: 8, action: "b", object: null, keyframe: 5 },
  ];
  if (activeSegmentId(1, overlap, null) !== "a") throw new Error("first only");
  if (activeSegmentId(3, overlap, "a") !== "b") throw new Error("latest started overlap");
  if (activeSegmentId(6, overlap, "b") !== "b") throw new Error("only later remains");
  const splitSrc: AnnotationSegment[] = [
    { id: "1", start: 0, end: 10, action: "pour", object: "cup", keyframe: 5 },
    { id: "2", start: 2, end: 4, action: "other", object: null, keyframe: 3 },
  ];
  if (splitSegmentAt(splitSrc, "1", 0, () => "x")) throw new Error("no split at start");
  if (splitSegmentAt(splitSrc, "1", 10, () => "x")) throw new Error("no split at end");
  if (splitSegmentAt(splitSrc, "missing", 5, () => "x")) throw new Error("unknown id");
  const after = splitSegmentAt(splitSrc, "1", 6, () => "1b");
  if (!after) throw new Error("split inside");
  if (after.length !== 3) throw new Error("inserts copy below");
  if (after[0].id !== "1" || after[0].end !== 6 || after[0].keyframe !== 5) throw new Error("top trimmed");
  if (after[1].id !== "1b" || after[1].start !== 6 || after[1].end !== 10 || after[1].action !== "pour") {
    throw new Error("copy below keeps labels");
  }
  if (after[1].keyframe !== 6) throw new Error("copy kf clamped into new range");
  if (after[2].id !== "2") throw new Error("later rows stay after the pair");
  const early = splitSegmentAt(splitSrc, "1", 3, () => "1b");
  if (!early || early[0].keyframe !== 3 || early[1].keyframe !== 5) throw new Error("kf follows the half that still contains it");
}

if (import.meta.env?.DEV) checkActiveSegment();
