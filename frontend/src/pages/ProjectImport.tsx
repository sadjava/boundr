import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import AnnotationMode from "../components/AnnotationMode";
import ConfirmDialog from "../components/ConfirmDialog";
import FilePick from "../components/FilePick";
import type { Project, Task } from "../types";

export default function ProjectImport() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [taskName, setTaskName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [withAnn, setWithAnn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    if (!id) return;
    api.get<Project>(`/api/projects/${id}`).then(setProject).catch((e) => setError(e.message));
  }, [id]);

  const canSubmit = !!file && !!taskName.trim();

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setError(null);
    setConfirm(true);
  }

  async function runImport() {
    if (!id || !file || !canSubmit) return;
    setImporting(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("with_annotations", withAnn ? "true" : "false");
      fd.append("task_name", taskName.trim());
      const task = await api.postForm<Task>(`/api/projects/${id}/import`, fd);
      navigate(`/tasks/${task.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
      setConfirm(false);
    } finally {
      setImporting(false);
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
      <h1 className="mt-3 mb-1 text-2xl font-semibold">Import archive</h1>
      <p className="mt-0 mb-6 text-sm text-[var(--color-muted)]">
        Creates a new task. Zip of videos, or <span className="font-mono">videos/</span> plus matching{" "}
        <span className="font-mono">annotations/</span> files.
      </p>
      <form onSubmit={onSubmit} className="grid gap-5">
        <label className="block text-sm">
          Task name <span className="text-[var(--color-accent)]">*</span>
          <input
            className="field"
            value={taskName}
            onChange={(e) => setTaskName(e.target.value)}
            required
            autoFocus
          />
        </label>
        <fieldset className="m-0 border-0 p-0">
          <legend className="text-sm">Archive</legend>
          <div className="mt-2">
            <FilePick accept=".zip,application/zip" file={file} onFile={setFile} />
          </div>
        </fieldset>
        <fieldset className="m-0 border-0 p-0">
          <legend className="text-sm">Contents</legend>
          <div className="mt-2">
            <AnnotationMode withAnnotations={withAnn} onChange={setWithAnn} />
          </div>
        </fieldset>
        {error && <p className="m-0 text-[var(--color-bad)]">{error}</p>}
        <div>
          <button type="submit" className="btn btn-primary px-4" disabled={!canSubmit}>
            Import
          </button>
        </div>
      </form>
      {confirm && file && (
        <ConfirmDialog
          title="Import archive?"
          body={`“${file.name}” will create task “${taskName.trim()}”${withAnn ? ", matching videos to annotations" : ""}.`}
          confirmLabel="Import"
          busyLabel="Importing…"
          variant="primary"
          busy={importing}
          onCancel={() => !importing && setConfirm(false)}
          onConfirm={runImport}
        />
      )}
    </div>
  );
}
