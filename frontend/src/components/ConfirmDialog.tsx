import { FormEvent } from "react";

export default function ConfirmDialog({
  title,
  body,
  confirmLabel = "Delete",
  busyLabel,
  variant = "danger",
  busy,
  onCancel,
  onConfirm,
}: {
  title: string;
  body: string;
  confirmLabel?: string;
  busyLabel?: string;
  variant?: "danger" | "primary";
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!busy) onConfirm();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#541A1A]/40 p-4"
      onClick={onCancel}
    >
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className="w-full max-w-md rounded-lg border border-[var(--color-line)] bg-[var(--color-panel)] p-5"
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            if (!busy) onCancel();
          }
        }}
      >
        <h2 id="confirm-title" className="mt-0 mb-2 text-lg font-semibold">
          {title}
        </h2>
        <p className="mt-0 mb-5 text-sm text-[var(--color-muted)]">{body}</p>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
          <button
            type="submit"
            className={`btn ${variant === "danger" ? "btn-danger-solid" : "btn-primary"}`}
            disabled={busy}
            autoFocus
          >
            {busy ? busyLabel || (variant === "danger" ? "Deleting…" : "Working…") : confirmLabel}
          </button>
        </div>
      </form>
    </div>
  );
}
