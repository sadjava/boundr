import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type { Project, Task } from "../types";

export default function TaskCreate() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!id) return;
    api.get<Project>(`/api/projects/${id}`).then(setProject).catch((e) => setError(e.message));
  }, [id]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!id || !name.trim()) return;
    setError(null);
    setSaving(true);
    try {
      const task = await api.post<Task>(`/api/projects/${id}/tasks`, { name: name.trim() });
      navigate(`/tasks/${task.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page max-w-xl">
      <Link
        to={id ? `/projects/${id}` : "/projects"}
        className="text-sm text-[var(--color-muted)] no-underline"
      >
        ← {project?.name || "Project"}
      </Link>
      <h1 className="mt-3 mb-1 text-2xl font-semibold">New task</h1>
      <p className="mt-0 mb-6 text-sm text-[var(--color-muted)]">
        A task is a batch of videos inside this project.
      </p>
      <form onSubmit={onSubmit} className="grid gap-5">
        <label className="block text-sm">
          Name <span className="text-[var(--color-accent)]">*</span>
          <input
            className="field"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoFocus
          />
        </label>
        {error && <p className="m-0 text-[var(--color-bad)]">{error}</p>}
        <div>
          <button type="submit" className="btn btn-primary px-4" disabled={saving || !name.trim()}>
            {saving ? "Creating…" : "Create task"}
          </button>
        </div>
      </form>
    </div>
  );
}
