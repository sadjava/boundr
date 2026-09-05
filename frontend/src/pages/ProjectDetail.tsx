import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, downloadProjectExport, downloadTaskExport } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import ExportDialog, { type ExportFormats } from "../components/ExportDialog";
import ListToolbar, { sortByDates, type SortState } from "../components/ListToolbar";
import type { Project, Task } from "../types";

export default function ProjectDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortState>({ field: "created", dir: "desc" });
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ kind: "project" } | { kind: "task"; task: Task } | null>(
    null,
  );
  const [deleting, setDeleting] = useState(false);
  const [exportTarget, setExportTarget] = useState<{ kind: "project" } | { kind: "task"; task: Task } | null>(
    null,
  );
  const [includeVideos, setIncludeVideos] = useState(false);
  const [formats, setFormats] = useState<ExportFormats>({ json: true, csv: false });
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    const [p, t] = await Promise.all([
      api.get<Project>(`/api/projects/${id}`),
      api.get<Task[]>(`/api/projects/${id}/tasks`),
    ]);
    setProject(p);
    setTasks(t);
  }, [id]);

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q ? tasks.filter((t) => t.name.toLowerCase().includes(q)) : tasks;
    return sortByDates(filtered, sort);
  }, [tasks, query, sort]);

  async function confirmDelete() {
    if (!pending) return;
    setDeleting(true);
    setError(null);
    try {
      if (pending.kind === "task") {
        await api.delete(`/api/tasks/${pending.task.id}`);
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

  async function runExport() {
    if (!exportTarget || !project) return;
    setExporting(true);
    setError(null);
    try {
      if (exportTarget.kind === "project") {
        await downloadProjectExport(project.id, includeVideos, formats, `${project.name}.zip`);
      } else {
        await downloadTaskExport(
          exportTarget.task.id,
          includeVideos,
          formats,
          `${exportTarget.task.name}.zip`,
        );
      }
      setExportTarget(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  if (!project) {
    return <p className="page text-[var(--color-muted)]">{error || "Loading…"}</p>;
  }

  const hasVideos = tasks.some((t) => t.video_count > 0);

  return (
    <div className="page">
      <Link to="/projects" className="text-sm text-[var(--color-muted)] no-underline">
        ← Projects
      </Link>
      <div className="mt-3 mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="m-0 text-2xl font-semibold">
            <span className="text-[var(--color-muted)]">Project</span>
            <span className="ml-2">{project.name}</span>
          </h1>
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
            Delete
          </button>
          <button
            className="btn btn-ghost"
            disabled={!hasVideos}
            onClick={() => {
              setIncludeVideos(false);
              setFormats({ json: true, csv: false });
              setExportTarget({ kind: "project" });
            }}
          >
            Export
          </button>
          <Link to={`/projects/${project.id}/import`} className="btn btn-ghost no-underline">
            Import archive
          </Link>
          <Link to={`/projects/${project.id}/tasks/new`} className="btn btn-primary no-underline">
            New task
          </Link>
        </div>
      </div>
      {error && <p className="text-[var(--color-bad)]">{error}</p>}

      <h2 className="mt-0 mb-3 text-lg font-semibold">Tasks</h2>
      <ListToolbar query={query} onQuery={setQuery} sort={sort} onSort={setSort} placeholder="Task name" />

      <div className="grid gap-2">
        {visible.length === 0 && (
          <p className="text-[var(--color-muted)]">
            {tasks.length === 0
              ? "No tasks yet. Create one or import an archive."
              : "No matching tasks."}
          </p>
        )}
        {visible.map((t) => (
          <div
            key={t.id}
            className="flex items-center gap-3 rounded-lg border border-[var(--color-line)] bg-[var(--color-panel)] px-4 py-3"
          >
            <Link to={`/tasks/${t.id}`} className="min-w-0 flex-1 text-[var(--color-text)] no-underline">
              <div className="font-medium">{t.name}</div>
              <div className="text-xs text-[var(--color-muted)]">
                {t.video_count} {t.video_count === 1 ? "video" : "videos"}
              </div>
            </Link>
            <button
              className="btn btn-ghost"
              disabled={t.video_count === 0}
              onClick={() => {
                setIncludeVideos(false);
                setFormats({ json: true, csv: false });
                setExportTarget({ kind: "task", task: t });
              }}
            >
              Export
            </button>
            <button className="btn btn-danger" onClick={() => setPending({ kind: "task", task: t })}>
              Delete
            </button>
          </div>
        ))}
      </div>
      {pending && (
        <ConfirmDialog
          title={pending.kind === "project" ? "Delete project?" : "Delete task?"}
          body={
            pending.kind === "project"
              ? `“${project.name}” and all of its tasks and videos will be removed. This cannot be undone.`
              : `“${pending.task.name}” and its videos will be removed. This cannot be undone.`
          }
          busy={deleting}
          onCancel={() => setPending(null)}
          onConfirm={confirmDelete}
        />
      )}
      {exportTarget && (
        <ExportDialog
          title={exportTarget.kind === "project" ? "Export project?" : "Export task?"}
          body={
            exportTarget.kind === "project"
              ? `Download “${project.name}” as a zip of its tasks.`
              : `Download “${exportTarget.task.name}” as a zip.`
          }
          includeVideos={includeVideos}
          onIncludeVideos={setIncludeVideos}
          formats={formats}
          onFormats={setFormats}
          busy={exporting}
          onCancel={() => !exporting && setExportTarget(null)}
          onConfirm={runExport}
        />
      )}
    </div>
  );
}
