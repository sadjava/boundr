import { ChangeEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import StatusBadge from "../components/StatusBadge";
import type { Project, Video } from "../types";

export default function ProjectDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [videos, setVideos] = useState<Video[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [pending, setPending] = useState<{ kind: "project" } | { kind: "video"; video: Video } | null>(
    null,
  );
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    const [p, v] = await Promise.all([
      api.get<Project>(`/api/projects/${id}`),
      api.get<Video[]>(`/api/projects/${id}/videos`),
    ]);
    setProject(p);
    setVideos(v);
  }, [id]);

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);

  useEffect(() => {
    const active = videos.some((v) => ["UPLOADING", "QUEUED", "PROCESSING"].includes(v.status));
    if (!active) return;
    const t = setInterval(() => {
      load().catch(() => undefined);
    }, 2000);
    return () => clearInterval(t);
  }, [videos, load]);

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !id) return;
    setError(null);
    setUploading(true);
    try {
      const created = await api.post<Video>(`/api/projects/${id}/videos`, {
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
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function confirmDelete() {
    if (!pending) return;
    setDeleting(true);
    setError(null);
    try {
      if (pending.kind === "video") {
        await api.delete(`/api/videos/${pending.video.id}`);
        setPending(null);
        await load();
      } else if (project) {
        await api.delete(`/api/projects/${project.id}`);
        navigate("/projects");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
      setPending(null);
    } finally {
      setDeleting(false);
    }
  }

  if (!project) {
    return <p className="page text-[var(--color-muted)]">{error || "Loading…"}</p>;
  }

  return (
    <div className="page">
      <Link to="/projects" className="text-sm text-[var(--color-muted)] no-underline">
        ← Projects
      </Link>
      <div className="mt-3 mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="m-0 text-2xl font-semibold">{project.name}</h1>
          {project.description && <p className="mt-1 text-[var(--color-muted)]">{project.description}</p>}
          {(project.action_types?.length || project.objects?.length) ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {(project.action_types || []).map((a) => (
              <span
                key={`a-${a}`}
                className="rounded-md border border-[var(--color-line)] bg-[var(--color-raised)] px-2 py-0.5 text-xs"
              >
                {a}
              </span>
            ))}
            {(project.objects || []).map((o) => (
              <span
                key={`o-${o}`}
                className="rounded-md border border-[var(--color-line)] px-2 py-0.5 text-xs text-[var(--color-muted)]"
              >
                {o}
              </span>
            ))}
          </div>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-danger" onClick={() => setPending({ kind: "project" })}>
            Delete project
          </button>
          <label className="btn btn-primary cursor-pointer px-4 py-2">
            {uploading ? "Uploading…" : "Upload video"}
            <input
              type="file"
              accept="video/mp4,video/*"
              className="hidden"
              disabled={uploading}
              onChange={onFile}
            />
          </label>
        </div>
      </div>
      {error && <p className="text-[var(--color-bad)]">{error}</p>}
      <div className="grid gap-2">
        {videos.length === 0 && (
          <p className="text-[var(--color-muted)]">No videos yet. Upload an MP4 to start a task.</p>
        )}
        {videos.map((v) => (
          <div
            key={v.id}
            className="flex items-center gap-3 rounded-lg border border-[var(--color-line)] bg-[var(--color-panel)] px-4 py-3"
          >
            <Link
              to={`/videos/${v.id}`}
              className="min-w-0 flex-1 text-[var(--color-text)] no-underline"
            >
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
          title={pending.kind === "project" ? "Delete project?" : "Delete video?"}
          body={
            pending.kind === "project"
              ? `“${project.name}” and all of its videos will be removed. This cannot be undone.`
              : `“${pending.video.name}” will be removed from this project. This cannot be undone.`
          }
          busy={deleting}
          onCancel={() => setPending(null)}
          onConfirm={confirmDelete}
        />
      )}
    </div>
  );
}
