import type { VideoStatus } from "../types";

const LABELS: Record<VideoStatus, string> = {
  UPLOADING: "Uploading",
  UPLOADED: "Uploaded",
  QUEUED: "Queued",
  PROCESSING: "Processing",
  COMPLETED: "Completed",
  FAILED: "Failed",
};

const DOT: Record<VideoStatus, string> = {
  UPLOADING: "bg-[var(--color-tertiary)]",
  UPLOADED: "bg-[var(--color-muted)]",
  QUEUED: "bg-[var(--color-warn)]",
  PROCESSING: "bg-[var(--color-warn)]",
  COMPLETED: "bg-[var(--color-ok)]",
  FAILED: "bg-[var(--color-bad)]",
};

export default function StatusBadge({ status }: { status: VideoStatus }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-[var(--color-text)]">
      <span className={`h-1.5 w-1.5 rounded-full ${DOT[status]}`} />
      {LABELS[status]}
    </span>
  );
}
