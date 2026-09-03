import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import type { Project } from "../types";

type SortKey = "created_desc" | "created_asc" | "updated_desc" | "updated_asc";

function fmt(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export default function Projects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("created_desc");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Project | null>(null);
  const [deleting, setDeleting] = useState(false);

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
    const copy = [...filtered];
    copy.sort((a, b) => {
      if (sort === "created_asc") return a.created_at.localeCompare(b.created_at);
      if (sort === "created_desc") return b.created_at.localeCompare(a.created_at);
      if (sort === "updated_asc") return a.updated_at.localeCompare(b.updated_at);
      return b.updated_at.localeCompare(a.updated_at);
    });
    return copy;
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

  return (
    <div className="page">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="m-0 text-2xl font-semibold">Projects</h1>
        <Link to="/projects/new" className="btn btn-primary no-underline">
          New project
        </Link>
      </div>
      <div className="mb-4 grid gap-3 sm:grid-cols-[1fr_auto]">
        <label className="block text-sm">
          Search
          <input
            className="field"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Name or description"
          />
        </label>
        <label className="block text-sm">
          Sort
          <select className="field" value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            <option value="created_desc">Created (newest)</option>
            <option value="created_asc">Created (oldest)</option>
            <option value="updated_desc">Updated (newest)</option>
            <option value="updated_asc">Updated (oldest)</option>
          </select>
        </label>
      </div>
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
            <Link
              to={`/projects/${p.id}`}
              className="min-w-0 flex-1 text-[var(--color-text)] no-underline"
            >
              <div className="font-medium">{p.name}</div>
              {p.description && (
                <div className="mt-1 text-sm text-[var(--color-muted)]">{p.description}</div>
              )}
              <div className="mt-1 text-xs text-[var(--color-muted)]">
                Created {fmt(p.created_at)} · Updated {fmt(p.updated_at)}
              </div>
            </Link>
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
    </div>
  );
}
