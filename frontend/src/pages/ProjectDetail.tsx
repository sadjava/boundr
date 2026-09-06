import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, downloadProjectExport, downloadTaskExport } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import ExportDialog, { type ExportFormats } from "../components/ExportDialog";
import InlineRename from "../components/InlineRename";
import ListToolbar, { sortByDates, type SortState } from "../components/ListToolbar";
import type { FineTune, Project, Task } from "../types";

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
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [ftOpen, setFtOpen] = useState(false);
  const [ftName, setFtName] = useState("");
  const [ftStarting, setFtStarting] = useState(false);
  const [ftStopping, setFtStopping] = useState(false);
  const [activeFt, setActiveFt] = useState<FineTune | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    const [p, t, fts] = await Promise.all([
      api.get<Project>(`/api/projects/${id}`),
      api.get<Task[]>(`/api/projects/${id}/tasks`),
      api.get<FineTune[]>(`/api/projects/${id}/fine-tunes`).catch(() => [] as FineTune[]),
    ]);
    setProject(p);
    setTasks(t);
    const inFlight = fts.find((f) => f.status === "QUEUED" || f.status === "PROCESSING");
    setActiveFt((prev) => {
      if (inFlight) return inFlight;
      if (prev && (prev.status === "QUEUED" || prev.status === "PROCESSING")) {
        const updated = fts.find((f) => f.id === prev.id);
        return updated ?? prev;
      }
      return prev;
    });
  }, [id]);

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);

  useEffect(() => {
    if (!activeFt || activeFt.status === "COMPLETED" || activeFt.status === "FAILED") return;
    const t = setInterval(() => {
      api
        .get<FineTune>(`/api/fine-tunes/${activeFt.id}`)
        .then(setActiveFt)
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(t);
  }, [activeFt]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q ? tasks.filter((t) => t.name.toLowerCase().includes(q)) : tasks;
    return sortByDates(filtered, sort);
  }, [tasks, query, sort]);

  const selectedTasks = useMemo(
    () => tasks.filter((t) => selected.has(t.id)),
    [tasks, selected],
  );
  const selectedAnnotated = selectedTasks.reduce((n, t) => n + (t.annotated_count || 0), 0);

  function toggleTask(task: Task) {
    if ((task.annotated_count || 0) === 0) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(task.id)) next.delete(task.id);
      else next.add(task.id);
      return next;
    });
  }

  async function confirmDelete() {
    if (!pending) return;
    setDeleting(true);
    setError(null);
    try {
      if (pending.kind === "task") {
        await api.delete(`/api/tasks/${pending.task.id}`);
        setSelected((prev) => {
          const next = new Set(prev);
          next.delete(pending.task.id);
          return next;
        });
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

  async function renameProject(name: string) {
    if (!project) return;
    setError(null);
    try {
      setProject(await api.patch<Project>(`/api/projects/${project.id}`, { name }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Rename failed");
      throw err;
    }
  }

  async function renameTask(task: Task, name: string) {
    setError(null);
    try {
      const updated = await api.patch<Task>(`/api/tasks/${task.id}`, { name });
      setTasks((rows) => rows.map((row) => (row.id === updated.id ? { ...row, ...updated } : row)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Rename failed");
      throw err;
    }
  }

  async function startFineTune() {
    if (!project || selected.size === 0) return;
    setFtStarting(true);
    setError(null);
    try {
      const body: { task_ids: string[]; name?: string } = {
        task_ids: Array.from(selected),
      };
      const trimmed = ftName.trim();
      if (trimmed) body.name = trimmed;
      const row = await api.post<FineTune>(`/api/projects/${project.id}/fine-tunes`, body);
      setActiveFt(row);
      setFtOpen(false);
      setFtName("");
      setSelected(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fine-tune failed to start");
    } finally {
      setFtStarting(false);
    }
  }

  async function cancelActiveFt() {
    if (!activeFt) return;
    setFtStopping(true);
    setError(null);
    try {
      setActiveFt(await api.post<FineTune>(`/api/fine-tunes/${activeFt.id}/cancel`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancel failed");
    } finally {
      setFtStopping(false);
    }
  }

  if (!project) {
    return <p className="page text-[var(--color-muted)]">{error || "Loading…"}</p>;
  }

  const hasVideos = tasks.some((t) => t.video_count > 0);
  const canFineTune = selected.size > 0 && selectedAnnotated > 0;
  const ftActive = activeFt?.status === "QUEUED" || activeFt?.status === "PROCESSING";

  return (
    <div className="page">
      <Link to="/projects" className="text-sm text-[var(--color-muted)] no-underline">
        ← Projects
      </Link>
      <div className="mt-3 mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="m-0 flex min-w-0 items-center text-2xl font-semibold">
            <span className="shrink-0 text-[var(--color-muted)]">Project</span>
            <InlineRename
              value={project.name}
              inputClassName="ml-2 min-w-[12rem] flex-1 text-2xl font-semibold"
              onSave={renameProject}
            >
              <span className="ml-2 min-w-0 truncate">{project.name}</span>
            </InlineRename>
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
      {activeFt && (activeFt.status === "COMPLETED" || activeFt.status === "FAILED") && (
        <p
          className={
            activeFt.status === "FAILED"
              ? "text-[var(--color-bad)]"
              : "text-[var(--color-ok)]"
          }
        >
          Fine-tune <code>{activeFt.name}</code>: {activeFt.status}
          {activeFt.status === "FAILED" && activeFt.error_msg
            ? ` — ${activeFt.error_msg.split("\n")[0]}`
            : null}
          {activeFt.status === "COMPLETED"
            ? " — available in the Model menu on tasks and videos."
            : null}
        </p>
      )}

      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="m-0 text-lg font-semibold">Tasks</h2>
        <button
          className={ftActive ? "btn btn-danger" : "btn btn-primary"}
          disabled={ftStopping || (!ftActive && (ftStarting || !canFineTune))}
          onClick={() => {
            if (ftActive) void cancelActiveFt();
            else setFtOpen(true);
          }}
          title={
            ftActive
              ? undefined
              : canFineTune
                ? undefined
                : "Select tasks that have annotated videos"
          }
        >
          {ftStopping
            ? "Stopping…"
            : ftActive
              ? "Stop"
              : ftStarting
                ? "Starting…"
                : `Fine-tune${selected.size > 0 ? ` (${selected.size})` : ""}`}
        </button>
      </div>
      <ListToolbar query={query} onQuery={setQuery} sort={sort} onSort={setSort} placeholder="Task name" />

      <div className="grid gap-2">
        {visible.length === 0 && (
          <p className="text-[var(--color-muted)]">
            {tasks.length === 0
              ? "No tasks yet. Create one or import an archive."
              : "No matching tasks."}
          </p>
        )}
        {visible.map((t) => {
          const selectable = (t.annotated_count || 0) > 0;
          return (
            <div
              key={t.id}
              role="link"
              tabIndex={0}
              className="flex cursor-pointer items-center gap-3 rounded-lg border border-[var(--color-line)] bg-[var(--color-panel)] px-4 py-3"
              onClick={(e) => {
                if ((e.target as HTMLElement).closest("button, input")) return;
                navigate(`/tasks/${t.id}`);
              }}
              onKeyDown={(e) => {
                if (e.key !== "Enter" && e.key !== " ") return;
                if ((e.target as HTMLElement).closest("button, input")) return;
                e.preventDefault();
                navigate(`/tasks/${t.id}`);
              }}
            >
              <input
                type="checkbox"
                className="shrink-0"
                checked={selected.has(t.id)}
                disabled={!selectable}
                onChange={() => toggleTask(t)}
                onClick={(e) => e.stopPropagation()}
                aria-label={`Select ${t.name} for fine-tune`}
                title={selectable ? undefined : "No annotated videos in this task"}
              />
              <div className="min-w-0 flex-1">
                <InlineRename
                  value={t.name}
                  onSave={(name) => renameTask(t, name)}
                >
                  <span className="min-w-0 truncate font-medium">{t.name}</span>
                </InlineRename>
                <div className="text-xs text-[var(--color-muted)]">
                  {t.video_count} {t.video_count === 1 ? "video" : "videos"}
                  {" · "}
                  {t.annotated_count || 0} annotated
                </div>
              </div>
              <button
                className="btn btn-ghost"
                disabled={t.video_count === 0}
                onClick={(e) => {
                  e.stopPropagation();
                  setIncludeVideos(false);
                  setFormats({ json: true, csv: false });
                  setExportTarget({ kind: "task", task: t });
                }}
              >
                Export
              </button>
              <button
                className="btn btn-danger"
                onClick={(e) => {
                  e.stopPropagation();
                  setPending({ kind: "task", task: t });
                }}
              >
                Delete
              </button>
            </div>
          );
        })}
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
      {ftOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#541A1A]/40 p-4"
          onClick={() => !ftStarting && setFtOpen(false)}
        >
          <form
            role="dialog"
            aria-modal="true"
            aria-labelledby="ft-title"
            className="w-full max-w-md rounded-lg border border-[var(--color-line)] bg-[var(--color-panel)] p-5"
            onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => {
              e.preventDefault();
              if (!ftStarting) void startFineTune();
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape" && !ftStarting) setFtOpen(false);
            }}
          >
            <h2 id="ft-title" className="mt-0 mb-2 text-lg font-semibold">
              Fine-tune Marlin?
            </h2>
            <p className="mt-0 mb-3 text-sm text-[var(--color-muted)]">
              {selected.size} {selected.size === 1 ? "task" : "tasks"}, {selectedAnnotated}{" "}
              annotated {selectedAnnotated === 1 ? "video" : "videos"}. Default name includes
              the project and date; checkpoint goes under your user S3 prefix.
            </p>
            <label className="mb-4 block text-sm text-[var(--color-muted)]">
              Name (optional)
              <input
                className="field mt-1 w-full"
                placeholder="marlin_ft_project_20260906_ab12"
                value={ftName}
                disabled={ftStarting}
                onChange={(e) => setFtName(e.target.value)}
                autoFocus
              />
            </label>
            <ul className="mt-0 mb-5 max-h-40 list-disc overflow-y-auto pl-5 text-sm">
              {selectedTasks.map((t) => (
                <li key={t.id}>
                  {t.name} ({t.annotated_count} annotated)
                </li>
              ))}
            </ul>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="btn btn-ghost"
                disabled={ftStarting}
                onClick={() => setFtOpen(false)}
              >
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={ftStarting || !canFineTune}>
                {ftStarting ? "Starting…" : "Start fine-tune"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
