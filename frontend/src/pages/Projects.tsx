import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, downloadProjectExport } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import ExportDialog, { type ExportFormats } from "../components/ExportDialog";
import InlineRename from "../components/InlineRename";
import ListToolbar, { sortByDates, type SortState } from "../components/ListToolbar";
import type { Project } from "../types";

function fmt(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export default function Projects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortState>({ field: "created", dir: "desc" });
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Project | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [exportingProject, setExportingProject] = useState<Project | null>(null);
  const [includeVideos, setIncludeVideos] = useState(false);
  const [formats, setFormats] = useState<ExportFormats>({ json: true, csv: false });
  const [exporting, setExporting] = useState(false);

  async function load() {
    setProjects(await api.get<Project[]>("/api/projects"));
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? projects.filter(
          (p) =>
            p.name.toLowerCase().includes(q) || (p.description || "").toLowerCase().includes(q),
        )
      : projects;
    return sortByDates(filtered, sort);
  }, [projects, query, sort]);

  async function remove() {
    if (!pending) return;
    setDeleting(true);
    setError(null);
    try {
      await api.delete(`/api/projects/${pending.id}`);
      setPending(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
  }

  async function renameProject(project: Project, name: string) {
    setError(null);
    try {
      const updated = await api.patch<Project>(`/api/projects/${project.id}`, { name });
      setProjects((rows) => rows.map((row) => (row.id === updated.id ? updated : row)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Rename failed");
      throw err;
    }
  }

  return (
    <div className="page">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="m-0 text-2xl font-semibold">Projects</h1>
        <Link to="/projects/new" className="btn btn-primary no-underline">
          New project
        </Link>
      </div>
      <ListToolbar
        query={query}
        onQuery={setQuery}
        sort={sort}
        onSort={setSort}
        placeholder="Name or description"
      />
      {error && <p className="text-[var(--color-bad)]">{error}</p>}
      <div className="grid gap-3">
        {visible.length === 0 && (
          <p className="text-[var(--color-muted)]">
            {projects.length === 0 ? "No projects yet." : "No matching projects."}
          </p>
        )}
        {visible.map((p) => (
          <div
            key={p.id}
            className="flex items-center gap-3 rounded-lg border border-[var(--color-line)] bg-[var(--color-panel)] px-5 py-4"
          >
            <div className="min-w-0 flex-1">
              <InlineRename value={p.name} onSave={(name) => renameProject(p, name)}>
                <Link
                  to={`/projects/${p.id}`}
                  className="min-w-0 truncate font-medium text-[var(--color-text)] no-underline"
                >
                  {p.name}
                </Link>
              </InlineRename>
              {p.description && (
                <div className="mt-1 text-sm text-[var(--color-muted)]">{p.description}</div>
              )}
              <div className="mt-1 text-xs text-[var(--color-muted)]">
                Created {fmt(p.created_at)} · Updated {fmt(p.updated_at)}
              </div>
            </div>
            <button
              className="btn btn-ghost"
              onClick={() => {
                setIncludeVideos(false);
                setFormats({ json: true, csv: false });
                setExportingProject(p);
              }}
            >
              Export
            </button>
            <button className="btn btn-danger" onClick={() => setPending(p)}>
              Delete
            </button>
          </div>
        ))}
      </div>
      {pending && (
        <ConfirmDialog
          title="Delete project?"
          body={`“${pending.name}” and all of its videos will be removed. This cannot be undone.`}
          busy={deleting}
          onCancel={() => setPending(null)}
          onConfirm={remove}
        />
      )}
      {exportingProject && (
        <ExportDialog
          title="Export project?"
          body={`Download “${exportingProject.name}” as a zip of its tasks.`}
          includeVideos={includeVideos}
          onIncludeVideos={setIncludeVideos}
          formats={formats}
          onFormats={setFormats}
          busy={exporting}
          onCancel={() => !exporting && setExportingProject(null)}
          onConfirm={async () => {
            setExporting(true);
            setError(null);
            try {
              await downloadProjectExport(
                exportingProject.id,
                includeVideos,
                formats,
                `${exportingProject.name}.zip`,
              );
              setExportingProject(null);
            } catch (err) {
              setError(err instanceof Error ? err.message : "Export failed");
            } finally {
              setExporting(false);
            }
          }}
        />
      )}
    </div>
  );
}
