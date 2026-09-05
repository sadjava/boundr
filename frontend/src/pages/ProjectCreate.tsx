import { FormEvent, KeyboardEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import type { Project } from "../types";

function addUnique(list: string[], raw: string) {
  const s = raw.trim();
  if (!s) return list;
  if (list.some((v) => v.toLowerCase() === s.toLowerCase())) return list;
  return [...list, s];
}

function ChipField({
  label,
  hint,
  values,
  onChange,
}: {
  label: string;
  hint: string;
  values: string[];
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  function add() {
    onChange(addUnique(values, draft));
    setDraft("");
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      add();
    }
  }

  return (
    <fieldset className="m-0 border-0 p-0">
      <legend className="text-sm">{label}</legend>
      <p className="mt-1 mb-2 text-sm text-[var(--color-muted)]">{hint}</p>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {values.map((v) => (
          <span
            key={v}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--color-line)] bg-[var(--color-raised)] px-2 py-0.5 text-sm"
          >
            {v}
            <button
              type="button"
              className="text-[var(--color-muted)]"
              onClick={() => onChange(values.filter((x) => x !== v))}
              aria-label={`Remove ${v}`}
            >
              ×
            </button>
          </span>
        ))}
        {values.length === 0 && (
          <span className="text-sm text-[var(--color-muted)]">None — open vocabulary</span>
        )}
      </div>
      <div className="flex gap-2">
        <input
          className="field mt-0"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
          placeholder="Type and press Enter"
        />
        <button type="button" className="btn btn-ghost shrink-0" onClick={add}>
          Add
        </button>
      </div>
    </fieldset>
  );
}

export default function ProjectCreate() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [actionTypes, setActionTypes] = useState<string[]>([]);
  const [objects, setObjects] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const created = await api.post<Project>("/api/projects", {
        name,
        description: description || null,
        action_types: actionTypes,
        objects,
      });
      navigate(`/projects/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page max-w-xl">
      <Link to="/projects" className="text-sm text-[var(--color-muted)] no-underline">
        ← Projects
      </Link>
      <h1 className="mt-3 mb-1 text-2xl font-semibold">New project</h1>
      <p className="mt-0 mb-6 text-sm text-[var(--color-muted)]">
        Leave action types and objects empty for open-vocabulary labeling. Add some only if you want
        quicker picks on the timeline and to restrict the model to those classes.
      </p>
      <form onSubmit={onSubmit} className="grid gap-5">
        <label className="block text-sm">
          Name <span className="text-[var(--color-accent)]">*</span>
          <input className="field" value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label className="block text-sm">
          Description <span className="text-[var(--color-muted)]">(optional)</span>
          <textarea
            className="field min-h-[5rem]"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <ChipField
          label="Action types"
          hint="Optional. Empty means free-form labels; specified classes restrict the model."
          values={actionTypes}
          onChange={setActionTypes}
        />
        <ChipField
          label="Objects"
          hint="Optional targets. Empty means the model (and you) can use any object, or none."
          values={objects}
          onChange={setObjects}
        />
        {error && <p className="m-0 text-[var(--color-bad)]">{error}</p>}
        <div>
          <button type="submit" className="btn btn-primary px-4" disabled={saving}>
            {saving ? "Creating…" : "Create project"}
          </button>
        </div>
      </form>
    </div>
  );
}
