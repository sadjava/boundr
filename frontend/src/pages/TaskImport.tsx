import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import AnnotationMode from "../components/AnnotationMode";
import ConfirmDialog from "../components/ConfirmDialog";
import FilePick from "../components/FilePick";
import type { Project, Task } from "../types";

export default function TaskImport() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [withAnn, setWithAnn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    if (!id) return;
    api
      .get<Task>(`/api/tasks/${id}`)
      .then(async (t) => {
        setTask(t);
        setProject(await api.get<Project>(`/api/projects/${t.project_id}`));
      })
      .catch((e) => setError(e.message));
  }, [id]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setError(null);
    setConfirm(true);
  }

  async function runImport() {
    if (!id || !file) return;
    setImporting(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("with_annotations", withAnn ? "true" : "false");
      await api.postForm<Task>(`/api/tasks/${id}/import`, fd);
      navigate(`/tasks/${id}`);
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
        to={id ? `/tasks/${id}` : "/projects"}
        className="text-sm text-[var(--color-muted)] no-underline"
      >
        ← {task?.name || "Task"}
      </Link>
      <h1 className="mt-3 mb-1 text-2xl font-semibold">Import archive</h1>
      <p className="mt-0 mb-6 text-sm text-[var(--color-muted)]">
        Adds videos to “{task?.name || "…"}”
        {project ? ` in ${project.name}` : ""}. Zip of videos, or{" "}
        <span className="font-mono">videos/</span> plus matching{" "}
        <span className="font-mono">annotations/</span> files.
      </p>
      <form onSubmit={onSubmit} className="grid gap-5">
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
          <button type="submit" className="btn btn-primary px-4" disabled={!file}>
            Import
          </button>
        </div>
      </form>
      {confirm && file && task && (
        <ConfirmDialog
          title="Import archive?"
          body={`“${file.name}” will be added to task “${task.name}”${withAnn ? ", matching videos to annotations" : ""}.`}
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
