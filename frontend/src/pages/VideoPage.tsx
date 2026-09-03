import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { activeSegmentId } from "../activeSegment";
import { api, downloadExport } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import StatusBadge from "../components/StatusBadge";
import Timeline, { colorFor } from "../components/Timeline";
import {
  INFERENCE_TYPES,
  type Annotation,
  type AnnotationData,
  type AnnotationSegment,
  type InferenceType,
  type Project,
  type Video,
} from "../types";

function emptyData(videoId: string, duration: number): AnnotationData {
  return { video_id: videoId, duration, segments: [] };
}

function coerceSegment(s: AnnotationSegment): AnnotationSegment {
  const start = s.start ?? 0;
  const end = s.end ?? 0;
  const kf = typeof s.keyframe === "number" ? s.keyframe : (start + end) / 2;
  return {
    ...s,
    action: s.action ?? "",
    object: s.object ?? null,
    start,
    end,
    keyframe: Math.min(end, Math.max(start, kf)),
  };
}

function newSegment(): AnnotationSegment {
  return { id: crypto.randomUUID(), start: 0, end: 0, action: "", object: null, keyframe: 0 };
}

const TIMELINE_H_MIN = 168;
const TIMELINE_H_MAX = 440;
const TIMELINE_H_DEFAULT = 248;
const VIDEO_H_MIN = 160;
const TL_H_KEY = "boundr-timeline-h";

function clampTimelineH(h: number, colH?: number) {
  const max = colH ? Math.min(TIMELINE_H_MAX, Math.max(TIMELINE_H_MIN, colH - VIDEO_H_MIN)) : TIMELINE_H_MAX;
  return Math.min(max, Math.max(TIMELINE_H_MIN, h));
}

function readTimelineH() {
  const n = Number(localStorage.getItem(TL_H_KEY));
  return Number.isFinite(n) ? clampTimelineH(n) : TIMELINE_H_DEFAULT;
}

export default function VideoPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const videoRef = useRef<HTMLVideoElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const tlHRef = useRef(TIMELINE_H_DEFAULT);
  const [tlH, setTlH] = useState(readTimelineH);
  const [video, setVideo] = useState<Video | null>(null);
  const [annotation, setAnnotation] = useState<Annotation | null>(null);
  const [data, setData] = useState<AnnotationData | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [mediaDuration, setMediaDuration] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [pipeline, setPipeline] = useState("overlap");
  const [inference, setInference] = useState<InferenceType[]>(INFERENCE_TYPES);
  const draggingRef = useRef(false);
  const dataRef = useRef(data);
  const selectedIdRef = useRef(selectedId);
  const pendingSeekRef = useRef<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [actionTypes, setActionTypes] = useState<string[]>([]);
  const [objectLabels, setObjectLabels] = useState<string[]>([]);
  dataRef.current = data;
  selectedIdRef.current = selectedId;
  tlHRef.current = tlH;

  const duration = mediaDuration || data?.duration || video?.duration || 0;

  const loadVideo = useCallback(async () => {
    if (!id) return;
    const v = await api.get<Video>(`/api/videos/${id}`);
    setVideo(v);
    try {
      const project = await api.get<Project>(`/api/projects/${v.project_id}`);
      setActionTypes(project.action_types || []);
      setObjectLabels(project.objects || []);
    } catch {
      /* keep defaults */
    }
    try {
      const ann = await api.get<Annotation>(`/api/videos/${id}/annotation`);
      setAnnotation(ann);
      setData({ ...ann.data, segments: ann.data.segments.map(coerceSegment) });
      setSelectedId((prev) => {
        if (prev && ann.data.segments.some((s) => s.id === prev)) return prev;
        return ann.data.segments[0]?.id ?? null;
      });
    } catch {
      /* none yet — user can annotate or run the model */
    }
  }, [id]);

  useEffect(() => {
    setVideo(null);
    setAnnotation(null);
    setData(null);
    setSelectedId(null);
    setCurrentTime(0);
    setMediaDuration(0);
    setError(null);
    loadVideo().catch((e) => setError(e.message));
  }, [loadVideo]);

  useEffect(() => {
    api
      .get<InferenceType[]>("/api/inference")
      .then(setInference)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!video) return;
    if (!["UPLOADING", "QUEUED", "PROCESSING"].includes(video.status)) return;
    const t = setInterval(() => {
      loadVideo().catch(() => undefined);
    }, 2000);
    return () => clearInterval(t);
  }, [video, loadVideo]);

  function ensureData(): AnnotationData {
    if (data) return data;
    const next = emptyData(id || "", duration);
    setData(next);
    return next;
  }

  function updateSegment(id: string, patch: Partial<AnnotationSegment>) {
    if (!data) return;
    setData({
      ...data,
      segments: data.segments.map((s) => {
        if (s.id !== id) return s;
        const next = { ...s, ...patch };
        next.keyframe = Math.min(next.end, Math.max(next.start, next.keyframe));
        return next;
      }),
    });
  }

  function addSegment() {
    const base = ensureData();
    const seg = newSegment();
    setData({ ...base, duration, segments: [...base.segments, seg] });
    setSelectedId(seg.id);
  }

  function removeSegment(sid: string) {
    if (!data) return;
    const next = data.segments.filter((s) => s.id !== sid);
    setData({ ...data, segments: next });
    setSelectedId((prev) => (prev === sid ? (next[0]?.id ?? null) : prev));
  }

  async function save() {
    if (!id || !data) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.put<Annotation>(`/api/videos/${id}/annotation`, {
        data: { ...data, duration },
      });
      setAnnotation(saved);
      setData(saved.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function runModel() {
    if (!id) return;
    setRunning(true);
    setError(null);
    try {
      await api.post(`/api/videos/${id}/process`, { pipeline });
      await loadVideo();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Run failed");
    } finally {
      setRunning(false);
    }
  }

  function startResize(e: ReactPointerEvent<HTMLButtonElement>) {
    if (e.button !== 0) return;
    e.preventDefault();
    const startY = e.clientY;
    const startH = tlH;
    const max = clampTimelineH(TIMELINE_H_MAX, sectionRef.current?.clientHeight);
    const move = (ev: PointerEvent) => {
      const next = clampTimelineH(startH + (startY - ev.clientY), sectionRef.current?.clientHeight);
      setTlH(Math.min(max, next));
    };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      localStorage.setItem(TL_H_KEY, String(tlHRef.current));
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  }

  function seek(t: number) {
    setCurrentTime(t);
    const el = videoRef.current;
    if (!el || el.readyState < 1) return;
    if (el.seeking) {
      pendingSeekRef.current = t;
      return;
    }
    pendingSeekRef.current = null;
    if (Math.abs(el.currentTime - t) < 0.001) return;
    el.currentTime = t;
  }

  function onSeeked() {
    const el = videoRef.current;
    const t = pendingSeekRef.current;
    pendingSeekRef.current = null;
    if (!el || t == null || Math.abs(el.currentTime - t) < 0.001) return;
    el.currentTime = t;
  }

  async function removeVideo() {
    if (!video) return;
    setDeleting(true);
    setError(null);
    try {
      await api.delete(`/api/videos/${video.id}`);
      navigate(`/projects/${video.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
      setDeleting(false);
      setConfirmDelete(false);
    }
  }

  if (!video) {
    return <p className="p-8 text-[var(--color-muted)]">{error || "Loading…"}</p>;
  }

  const busy = video.status === "QUEUED" || video.status === "PROCESSING";
  const canRun = video.status !== "UPLOADING" && !busy;

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] min-h-0 flex-col overflow-hidden">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--color-line)] px-5 py-3">
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <Link
            to={`/projects/${video.project_id}`}
            className="text-sm text-[var(--color-muted)] no-underline"
          >
            ← Project
          </Link>
          <h1 className="m-0 truncate text-base font-semibold">{video.name}</h1>
          <StatusBadge status={video.status} />
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-ghost" disabled={!video.prev_video_id} onClick={() => video.prev_video_id && navigate(`/videos/${video.prev_video_id}`)}>
            Previous
          </button>
          <button className="btn btn-ghost" disabled={!video.next_video_id} onClick={() => video.next_video_id && navigate(`/videos/${video.next_video_id}`)}>
            Next
          </button>
          <label className="flex items-center gap-2 text-sm text-[var(--color-muted)]">
            Model
            <select
              className="field mt-0 w-44"
              value={pipeline}
              disabled={!canRun || running}
              onChange={(e) => setPipeline(e.target.value)}
              title={inference.find((m) => m.id === pipeline)?.description}
            >
              {inference.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
          <button className="btn btn-primary" disabled={!canRun || running} onClick={runModel}>
            {busy ? "Running model…" : running ? "Starting…" : "Run model"}
          </button>
          <button className="btn btn-ghost" disabled={saving || !data} onClick={save}>
            {saving ? "Saving…" : "Save"}
          </button>
          <button className="btn btn-danger" onClick={() => setConfirmDelete(true)}>
            Delete
          </button>
        </div>
      </div>

      {error && <p className="px-5 pt-3 text-sm text-[var(--color-bad)]">{error}</p>}
      {video.status === "FAILED" && (
        <div className="mx-5 mt-3 rounded-lg border border-[var(--color-bad)] px-4 py-3 text-sm">
          {video.latest_job?.error_msg || "Processing failed"}
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_300px]">
        <section ref={sectionRef} className="flex min-h-0 min-w-0 flex-col">
          <div className="video-well">
            {video.playback_url ? (
              <div className="video-stage">
                <video
                  ref={videoRef}
                  src={video.playback_url}
                  controls
                  muted
                  preload="auto"
                  className="video-frame"
                  onLoadedMetadata={(e) => {
                    const d = e.currentTarget.duration || 0;
                    setMediaDuration(d);
                    setData((prev) => prev ?? emptyData(video.id, d));
                  }}
                  onSeeked={onSeeked}
                  onTimeUpdate={(e) => {
                    if (draggingRef.current) return;
                    const el = e.currentTarget;
                    const t = el.currentTime;
                    setCurrentTime(t);
                    if (el.paused) return;
                    const segs = dataRef.current?.segments;
                    if (!segs?.length) return;
                    const next = activeSegmentId(t, segs, selectedIdRef.current);
                    if (next && next !== selectedIdRef.current) setSelectedId(next);
                  }}
                />
              </div>
            ) : (
              <div className="text-sm text-[var(--color-line)]">Waiting for upload…</div>
            )}
          </div>
          <div
            className="relative flex shrink-0 flex-col overflow-hidden border-t border-[var(--color-line)] bg-[var(--color-panel)]"
            style={{ height: tlH }}
          >
            <button
              type="button"
              className="tl-split"
              aria-label="Resize timeline"
              onPointerDown={startResize}
            />
            <div className="flex min-h-0 flex-1 flex-col px-5 pb-3 pt-4">
              <div className="mb-2 flex items-center justify-between text-xs text-[var(--color-muted)]">
                <span>
                  Timeline · {data?.segments.length ?? 0} segments
                </span>
                <span className="font-mono">{currentTime.toFixed(2)}s</span>
              </div>
              {data && duration > 0 && (
                <div className="min-h-0 flex-1">
                  <Timeline
                    duration={duration}
                    segments={data.segments}
                    selectedId={selectedId}
                    currentTime={currentTime}
                    actionTypes={actionTypes}
                    objectLabels={objectLabels}
                    onSelect={setSelectedId}
                    onSeek={seek}
                    onAdd={addSegment}
                    onRemove={removeSegment}
                    onMeta={(sid, patch) => updateSegment(sid, patch)}
                    onDragStart={() => {
                      draggingRef.current = true;
                      videoRef.current?.pause();
                    }}
                    onDragEnd={() => {
                      draggingRef.current = false;
                      const el = videoRef.current;
                      const t = pendingSeekRef.current;
                      pendingSeekRef.current = null;
                      if (el && t != null && !el.seeking) el.currentTime = t;
                    }}
                    onChange={(sid, start, end, keyframe) =>
                      updateSegment(sid, { start, end, keyframe })
                    }
                  />
                </div>
              )}
            </div>
          </div>
        </section>

        <aside className="flex min-h-0 flex-col overflow-hidden border-l border-[var(--color-line)] bg-[var(--color-panel)]">
          <div className="flex items-center justify-between border-b border-[var(--color-line)] px-4 py-3">
            <span className="text-sm font-medium">Segments</span>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {(data?.segments.length ?? 0) === 0 && (
              <p className="px-4 py-6 text-sm text-[var(--color-muted)]">
                No segments yet. Add an action under the timeline, or run the model.
              </p>
            )}
            {data?.segments.map((seg, i) => {
              const active = seg.id === selectedId;
              const color = colorFor(i);
              return (
                <div
                  key={seg.id}
                  className={`flex cursor-pointer items-center gap-2 border-b border-[var(--color-line)] px-4 py-2.5 ${
                    active ? "" : "hover:bg-[var(--color-raised)]"
                  }`}
                  style={{
                    borderLeft: `3px solid ${color}`,
                    background: active ? `${color}1A` : undefined,
                  }}
                  onClick={() => {
                    setSelectedId(seg.id);
                    if (seg.end - seg.start >= 0.05) seek(seg.start);
                  }}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">
                      {seg.action || "untitled"}
                      <span className="font-normal text-[var(--color-tertiary)]">
                        {" "}
                        · {seg.object ?? "none"}
                      </span>
                    </div>
                    <div className="font-mono text-[11px] text-[var(--color-muted)]">
                      {seg.end - seg.start < 0.05
                        ? "no range"
                        : `${seg.start.toFixed(2)}s – ${seg.end.toFixed(2)}s · kf ${seg.keyframe.toFixed(2)}s`}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="border-0 bg-transparent px-1 text-sm leading-none text-[var(--color-tertiary)] hover:text-[var(--color-bad)]"
                    aria-label="Remove"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeSegment(seg.id);
                    }}
                  >
                    ×
                  </button>
                </div>
              );
            })}
          </div>
          <div className="flex gap-2 border-t border-[var(--color-line)] px-4 py-4">
            <button
              className="btn btn-ghost flex-1"
              disabled={!annotation}
              onClick={() =>
                downloadExport(video.id, "json", `${video.name}.annotation.json`).catch((e) =>
                  setError(e.message),
                )
              }
            >
              JSON
            </button>
            <button
              className="btn btn-ghost flex-1"
              disabled={!annotation}
              onClick={() =>
                downloadExport(video.id, "csv", `${video.name}.annotation.csv`).catch((e) =>
                  setError(e.message),
                )
              }
            >
              CSV
            </button>
          </div>
        </aside>
      </div>
      {confirmDelete && (
        <ConfirmDialog
          title="Delete video?"
          body={`“${video.name}” will be removed from this project. This cannot be undone.`}
          busy={deleting}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={removeVideo}
        />
      )}
    </div>
  );
}
