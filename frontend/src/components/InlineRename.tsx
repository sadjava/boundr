import { useEffect, useRef, useState, type ReactNode } from "react";

export default function InlineRename({
  value,
  onSave,
  children,
  inputClassName = "text-base font-medium",
}: {
  value: string;
  onSave: (name: string) => Promise<void>;
  children: ReactNode;
  inputClassName?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const pending = useRef(false);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [editing, value]);

  useEffect(() => {
    if (!editing) return;
    const el = inputRef.current;
    if (!el) return;
    el.focus();
    el.select();
  }, [editing]);

  async function commit() {
    if (pending.current) return;
    const next = draft.trim();
    if (!next || next === value) {
      setDraft(value);
      setEditing(false);
      return;
    }
    pending.current = true;
    setBusy(true);
    try {
      await onSave(next);
      setEditing(false);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        className={`min-w-[8rem] border-0 border-b border-[var(--color-accent)] bg-transparent px-0 py-0 outline-none ${inputClassName}`}
        value={draft}
        disabled={busy}
        maxLength={255}
        aria-label="Name"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          void commit();
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            void commit();
          }
          if (e.key === "Escape") {
            e.preventDefault();
            setDraft(value);
            setEditing(false);
          }
        }}
      />
    );
  }

  return (
    <span className="inline-flex min-w-0 max-w-full items-center gap-1">
      {children}
      <button
        type="button"
        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded border-0 bg-transparent p-0 text-[var(--color-tertiary)] hover:bg-[var(--color-raised)] hover:text-[var(--color-accent)]"
        aria-label="Rename"
        title="Rename"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setDraft(value);
          setEditing(true);
        }}
      >
        <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden>
          <path
            fill="currentColor"
            d="M11.1 1.6c.5-.5 1.4-.5 1.9 0l1.4 1.4c.5.5.5 1.4 0 1.9L5.6 13.7 2 14.8l1.1-3.6zM12.3 2.7 4.4 10.6l.8.8 7.9-7.9z"
          />
        </svg>
      </button>
    </span>
  );
}
