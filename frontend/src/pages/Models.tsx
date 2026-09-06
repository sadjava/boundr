import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import StatusBadge from "../components/StatusBadge";
import type { FineTune, VideoStatus } from "../types";

function fmt(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function manifestStats(ft: FineTune): { videos: number; segments: number } {
  const m = ft.manifest;
  if (!m) return { videos: 0, segments: 0 };
  const videos = typeof m.video_count === "number" ? m.video_count : 0;
  const list = Array.isArray(m.videos) ? m.videos : [];
  const segments = list.reduce((sum, item) => {
    if (item && typeof item === "object" && "segment_count" in item) {
      const n = (item as { segment_count?: unknown }).segment_count;
      return sum + (typeof n === "number" ? n : 0);
    }
    return sum;
  }, 0);
  return { videos, segments };
}

export default function Models() {
  const [rows, setRows] = useState<FineTune[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<FineTune | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function load() {
    setRows(await api.get<FineTune[]>("/api/fine-tunes"));
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  const empty = useMemo(() => rows.length === 0, [rows]);

  async function toggleHidden(ft: FineTune) {
    setBusyId(ft.id);
    setError(null);
    try {
      const updated = await api.patch<FineTune>(`/api/fine-tunes/${ft.id}`, {
        hidden: !ft.hidden,
      });
      setRows((list) => list.map((r) => (r.id === updated.id ? updated : r)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setBusyId(null);
    }
  }

  async function remove() {
    if (!pendingDelete) return;
    setDeleting(true);
    setError(null);
    try {
      await api.delete(`/api/fine-tunes/${pendingDelete.id}`);
      setRows((list) => list.filter((r) => r.id !== pendingDelete.id));
      setPendingDelete(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="page">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="m-0 text-2xl font-semibold">Models</h1>
          <p className="mt-1 mb-0 text-sm text-[var(--color-muted)]">
            Your fine-tuned Marlin checkpoints. Hide removes a model from the inference menu;
            delete removes the row and S3 artifacts.
          </p>
        </div>
      </div>

      {error && <p className="mb-4 text-sm text-[var(--color-bad)]">{error}</p>}

      {empty ? (
        <p className="text-sm text-[var(--color-muted)]">
          No fine-tunes yet. Start one from a{" "}
          <Link to="/projects" className="text-[var(--color-accent)]">
            project
          </Link>{" "}
          page.
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {rows.map((ft) => {
            const stats = manifestStats(ft);
            const open = expanded === ft.id;
            const videoList = Array.isArray(ft.manifest?.videos) ? ft.manifest.videos : [];
            return (
              <li
                key={ft.id}
                className={`rounded-lg border border-[var(--color-line)] bg-[var(--color-panel)] p-4 ${
                  ft.hidden ? "opacity-70" : ""
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="m-0 text-base font-semibold text-[var(--color-text)]">
                        {ft.display_name}
                      </h2>
                      <StatusBadge status={ft.status as VideoStatus} />
                      {ft.hidden && (
                        <span className="text-[11px] font-medium text-[var(--color-muted)]">
                          Hidden from menu
                        </span>
                      )}
                    </div>
                    <p className="mt-1 mb-0 font-mono text-xs text-[var(--color-muted)]">{ft.name}</p>
                    <p className="mt-2 mb-0 text-sm text-[var(--color-muted)]">
                      {ft.project_name ? (
                        ft.project_id ? (
                          <Link
                            to={`/projects/${ft.project_id}`}
                            className="text-[var(--color-accent)] no-underline hover:underline"
                          >
                            {ft.project_name}
                          </Link>
                        ) : (
                          ft.project_name
                        )
                      ) : (
                        <span>Project deleted</span>
                      )}
                      {" · "}
                      {fmt(ft.created_at)}
                      {ft.status === "COMPLETED" && (
                        <>
                          {" · "}
                          {stats.videos} video{stats.videos === 1 ? "" : "s"}
                          {" · "}
                          {stats.segments} segment{stats.segments === 1 ? "" : "s"}
                        </>
                      )}
                    </p>
                    {ft.task_names.length > 0 && (
                      <p className="mt-1 mb-0 text-sm text-[var(--color-muted)]">
                        Tasks: {ft.task_names.join(", ")}
                      </p>
                    )}
                    {ft.error_msg && ft.status === "FAILED" && (
                      <p className="mt-2 mb-0 line-clamp-2 text-sm text-[var(--color-bad)]">
                        {ft.error_msg}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    {ft.status === "COMPLETED" && (
                      <button
                        type="button"
                        className="btn btn-ghost py-1"
                        disabled={busyId === ft.id}
                        onClick={() => void toggleHidden(ft)}
                      >
                        {ft.hidden ? "Show in menu" : "Hide from menu"}
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn btn-ghost py-1"
                      onClick={() => setExpanded(open ? null : ft.id)}
                    >
                      {open ? "Hide data" : "Training data"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost py-1 text-[var(--color-bad)]"
                      onClick={() => setPendingDelete(ft)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
                {open && (
                  <div className="mt-3 border-t border-[var(--color-line)] pt-3 text-sm">
                    {!ft.manifest ? (
                      <p className="m-0 text-[var(--color-muted)]">
                        No manifest yet (job not completed).
                      </p>
                    ) : (
                      <>
                        <p className="mt-0 mb-2 text-[var(--color-muted)]">
                          {stats.videos} video{stats.videos === 1 ? "" : "s"}, {stats.segments}{" "}
                          segment{stats.segments === 1 ? "" : "s"}
                          {typeof ft.manifest.total_bytes === "number"
                            ? ` · ${(ft.manifest.total_bytes / (1024 * 1024)).toFixed(1)} MB`
                            : ""}
                          {ft.manifest.mocked === true ? " · mock train" : ""}
                        </p>
                        {videoList.length > 0 ? (
                          <ul className="m-0 max-h-48 list-none overflow-y-auto p-0 text-xs text-[var(--color-muted)]">
                            {videoList.map((item, i) => {
                              const v =
                                item && typeof item === "object"
                                  ? (item as {
                                      video_id?: string;
                                      segment_count?: number;
                                      bytes?: number;
                                    })
                                  : {};
                              return (
                                <li key={v.video_id || i} className="py-0.5 font-mono">
                                  {v.video_id ?? "?"}
                                  {typeof v.segment_count === "number"
                                    ? ` · ${v.segment_count} seg`
                                    : ""}
                                  {typeof v.bytes === "number"
                                    ? ` · ${(v.bytes / 1024).toFixed(0)} KB`
                                    : ""}
                                </li>
                              );
                            })}
                          </ul>
                        ) : null}
                      </>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {pendingDelete && (
        <ConfirmDialog
          title="Delete model?"
          body={`Remove “${pendingDelete.display_name}” (${pendingDelete.name}) and its S3 checkpoint. This cannot be undone.`}
          confirmLabel="Delete"
          busy={deleting}
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => void remove()}
        />
      )}
    </div>
  );
}
