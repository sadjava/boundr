export type ExportFormats = { json: boolean; csv: boolean };

export default function ExportDialog({
  title,
  body,
  includeVideos,
  onIncludeVideos,
  formats,
  onFormats,
  busy,
  onCancel,
  onConfirm,
}: {
  title: string;
  body: string;
  includeVideos: boolean;
  onIncludeVideos: (next: boolean) => void;
  formats: ExportFormats;
  onFormats: (next: ExportFormats) => void;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const canExport = formats.json || formats.csv;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#541A1A]/40 p-4"
      onClick={onCancel}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="export-title"
        className="w-full max-w-md rounded-lg border border-[var(--color-line)] bg-[var(--color-panel)] p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="export-title" className="mt-0 mb-2 text-lg font-semibold">
          {title}
        </h2>
        <p className="mt-0 mb-4 text-sm text-[var(--color-muted)]">{body}</p>
        <div className="mb-3 flex flex-wrap gap-2">
          <button
            type="button"
            className={`btn ${includeVideos ? "btn-ghost" : "btn-primary"}`}
            disabled={busy}
            onClick={() => onIncludeVideos(false)}
          >
            Annotations only
          </button>
          <button
            type="button"
            className={`btn ${includeVideos ? "btn-primary" : "btn-ghost"}`}
            disabled={busy}
            onClick={() => onIncludeVideos(true)}
          >
            With videos
          </button>
        </div>
        <div className="mb-5 flex flex-wrap gap-2">
          <button
            type="button"
            className={`btn ${formats.json ? "btn-primary" : "btn-ghost"}`}
            disabled={busy}
            onClick={() => onFormats({ ...formats, json: !formats.json })}
          >
            JSON
          </button>
          <button
            type="button"
            className={`btn ${formats.csv ? "btn-primary" : "btn-ghost"}`}
            disabled={busy}
            onClick={() => onFormats({ ...formats, csv: !formats.csv })}
          >
            CSV
          </button>
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || !canExport}
            onClick={onConfirm}
          >
            {busy ? "Exporting…" : "Export"}
          </button>
        </div>
      </div>
    </div>
  );
}
