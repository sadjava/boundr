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
}

if (import.meta.env?.DEV) checkActiveSegment();
