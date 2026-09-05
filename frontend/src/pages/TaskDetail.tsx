import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, downloadTaskExport } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import ExportDialog, { type ExportFormats } from "../components/ExportDialog";
import ListToolbar, { sortByDates, type SortState } from "../components/ListToolbar";
import StatusBadge from "../components/StatusBadge";
import { INFERENCE_TYPES, type InferenceType, type Project, type Task, type Video } from "../types";

export default function TaskDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [videos, setVideos] = useState<Video[]>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortState>({ field: "created", dir: "desc" });
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [includeVideos, setIncludeVideos] = useState(false);
  const [formats, setFormats] = useState<ExportFormats>({ json: true, csv: false });
  const [exporting, setExporting] = useState(false);
  const [pipeline, setPipeline] = useState("marlin");
  const [inference, setInference] = useState<InferenceType[]>(INFERENCE_TYPES);
  const [running, setRunning] = useState(false);
  const [pending, setPending] = useState<{ kind: "task" } | { kind: "video"; video: Video } | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    const t = await api.get<Task>(`/api/tasks/${id}`);
    const [p, v] = await Promise.all([
      api.get<Project>(`/api/projects/${t.project_id}`),
      api.get<Video[]>(`/api/tasks/${id}/videos`),
    ]);
    setTask(t);
    setProject(p);
    setVideos(v);
  }, [id]);

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);

  useEffect(() => {
    api.get<InferenceType[]>("/api/inference").then(setInference).catch(() => undefined);
  }, []);

  useEffect(() => {
    const active = videos.some((v) => ["UPLOADING", "QUEUED", "PROCESSING"].includes(v.status));
    if (!active) return;
    const t = setInterval(() => {
      load().catch(() => undefined);
    }, 2000);
    return () => clearInterval(t);
  }, [videos, load]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q ? videos.filter((v) => v.name.toLowerCase().includes(q)) : videos;
    return sortByDates(filtered, sort);
  }, [videos, query, sort]);

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (!files.length || !id) return;
    setError(null);
    setUploading(true);
    try {
      for (const file of files) {
        const created = await api.post<Video>(`/api/tasks/${id}/videos`, {
          name: file.name,
          content_type: file.type || "video/mp4",
        });
        if (!created.upload_url) throw new Error("Missing upload URL");
        const put = await fetch(created.upload_url, {
          method: "PUT",
          body: file,
          headers: { "Content-Type": file.type || "video/mp4" },
        });
        if (!put.ok) throw new Error(`S3 upload failed (${put.status})`);
        await api.post(`/api/videos/${created.id}/uploaded`);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function onExport() {
    if (!task) return;
    setExporting(true);
    setError(null);
    try {
      await downloadTaskExport(task.id, includeVideos, formats, `${task.name}.zip`);
      setExportOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  async function runAll() {
    if (!id) return;
    setRunning(true);
    setError(null);
    try {
      await api.post(`/api/tasks/${id}/process`, { pipeline });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start inference");
    } finally {
      setRunning(false);
    }
  }

  async function confirmDelete() {
    if (!pending || !task) return;
    setDeleting(true);
    setError(null);
    try {
      if (pending.kind === "video") {
        await api.delete(`/api/videos/${pending.video.id}`);
        setPending(null);
        await load();
      } else {
        await api.delete(`/api/tasks/${task.id}`);
        navigate(`/projects/${task.project_id}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
      setPending(null);
    } finally {
      setDeleting(false);
    }
  }

  if (!task) {
    return <p className="page text-[var(--color-muted)]">{error || "Loading…"}</p>;
  }

  const ready = videos.filter((v) => v.status !== "UPLOADING");
  const busy = videos.some((v) => v.status === "QUEUED" || v.status === "PROCESSING");

  return (
    <div className="page">
      <Link to={`/projects/${task.project_id}`} className="text-sm text-[var(--color-muted)] no-underline">
        ← {project?.name || "Project"}
      </Link>
      <div className="mt-3 mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="m-0 text-2xl font-semibold">
            <span className="text-[var(--color-muted)]">Task</span>
            <span className="ml-2">{task.name}</span>
          </h1>
          <p className="mt-1 text-sm text-[var(--color-muted)]">
            {videos.length} {videos.length === 1 ? "video" : "videos"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-danger" onClick={() => setPending({ kind: "task" })}>
            Delete
          </button>
          <button
            className="btn btn-ghost"
            disabled={videos.length === 0}
            onClick={() => {
              setIncludeVideos(false);
              setFormats({ json: true, csv: false });
              setExportOpen(true);
            }}
          >
            Export
          </button>
          <Link to={`/tasks/${task.id}/import`} className="btn btn-ghost no-underline">
            Import archive
          </Link>
          <label className="btn btn-primary cursor-pointer px-4 py-2">
            {uploading ? "Uploading…" : "Upload videos"}
            <input
              type="file"
              accept="video/mp4,video/*"
              multiple
              className="hidden"
              disabled={uploading}
              onChange={onFile}
            />
          </label>
        </div>
      </div>
      {error && <p className="text-[var(--color-bad)]">{error}</p>}

      <div className="mb-6 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm text-[var(--color-muted)]">
          Model
          <select
            className="field mt-0 w-44"
            value={pipeline}
            disabled={running || ready.length === 0}
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
        <button
          className="btn btn-primary"
          disabled={running || ready.length === 0}
          onClick={runAll}
        >
          {busy ? "Running…" : running ? "Starting…" : "Run all videos"}
        </button>
      </div>

      <h2 className="mt-0 mb-3 text-lg font-semibold">Videos</h2>
      <ListToolbar query={query} onQuery={setQuery} sort={sort} onSort={setSort} placeholder="Video name" />

      <div className="grid gap-2">
        {visible.length === 0 && (
          <p className="text-[var(--color-muted)]">
            {videos.length === 0
              ? "No videos yet. Upload files or import a zip."
              : "No matching videos."}
          </p>
        )}
        {visible.map((v) => (
          <div
            key={v.id}
            className="flex items-center gap-3 rounded-lg border border-[var(--color-line)] bg-[var(--color-panel)] px-4 py-3"
          >
            <Link to={`/videos/${v.id}`} className="min-w-0 flex-1 text-[var(--color-text)] no-underline">
              <div className="font-medium">{v.name}</div>
              <div className="font-mono text-xs text-[var(--color-muted)]">
                {v.duration ? `${v.duration.toFixed(1)}s` : "ready to annotate"}
              </div>
            </Link>
            <StatusBadge status={v.status} />
            <button className="btn btn-danger" onClick={() => setPending({ kind: "video", video: v })}>
              Delete
            </button>
          </div>
        ))}
      </div>
      {pending && (
        <ConfirmDialog
          title={pending.kind === "task" ? "Delete task?" : "Delete video?"}
          body={
            pending.kind === "task"
              ? `“${task.name}” and all of its videos will be removed. This cannot be undone.`
              : `“${pending.video.name}” will be removed from this task. This cannot be undone.`
          }
          busy={deleting}
          onCancel={() => setPending(null)}
          onConfirm={confirmDelete}
        />
      )}
      {exportOpen && (
        <ExportDialog
          title="Export task?"
          body={`Download “${task.name}” as a zip.`}
          includeVideos={includeVideos}
          onIncludeVideos={setIncludeVideos}
          formats={formats}
          onFormats={setFormats}
          busy={exporting}
          onCancel={() => !exporting && setExportOpen(false)}
          onConfirm={onExport}
        />
      )}
    </div>
  );
}
