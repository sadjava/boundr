import { useEffect, useRef, useState } from "react";
import { type AnnotationSegment } from "../types";
import RangeSlider from "./RangeSlider";

export const TRACK_COLORS = [
  "#C1502E",
  "#C9932B",
  "#5C6B3D",
  "#8C4A2F",
  "#B5657A",
  "#5B3A5E",
  "#8A6D3A",
];

export function colorFor(i: number) {
  return TRACK_COLORS[i % TRACK_COLORS.length];
}

function CatalogSelect({
  value,
  options,
  ariaLabel,
  muted,
  onFocus,
  onChange,
}: {
  value: string;
  options: string[];
  ariaLabel: string;
  muted?: boolean;
  onFocus: () => void;
  onChange: (v: string) => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [box, setBox] = useState({ bottom: 0, left: 0, width: 0, maxHeight: 192 });
  const items = value && !options.includes(value) ? [value, ...options] : options;

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent && e.key !== "Escape") return;
      if (e instanceof KeyboardEvent || !root.current?.contains(e.target as Node)) setOpen(false);
    };
    const onScroll = (e: Event) => {
      const menu = root.current?.querySelector(".label-menu");
      if (menu && (e.target === menu || menu.contains(e.target as Node))) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    document.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
      document.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  return (
    <div ref={root} className="relative min-w-0 flex-1">
      <button
        type="button"
        className={`label-select${muted ? " muted" : ""}`}
        aria-label={ariaLabel}
        aria-expanded={open}
        onClick={(e) => {
          onFocus();
          if (open) {
            setOpen(false);
            return;
          }
          const r = e.currentTarget.getBoundingClientRect();
          setBox({
            bottom: window.innerHeight - r.top + 2,
            left: r.left,
            width: r.width,
            maxHeight: Math.min(192, Math.max(80, r.top - 8)),
          });
          setOpen(true);
        }}
      >
        {value}
      </button>
      {open && (
        <ul
          className="label-menu"
          role="listbox"
          style={{ bottom: box.bottom, left: box.left, width: box.width, maxHeight: box.maxHeight }}
        >
          {items.map((o) => (
            <li key={o} role="presentation">
              <button
                type="button"
                role="option"
                aria-selected={o === value}
                className={o === value ? "on" : undefined}
                onClick={() => {
                  onChange(o);
                  setOpen(false);
                }}
              >
                {o}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function LabelField({
  value,
  options,
  ariaLabel,
  placeholder,
  className,
  muted,
  onFocus,
  onChange,
}: {
  value: string;
  options: string[];
  ariaLabel: string;
  placeholder: string;
  className: string;
  muted?: boolean;
  onFocus: () => void;
  onChange: (v: string) => void;
}) {
  if (!options.length) {
    return (
      <input
        className={className}
        aria-label={ariaLabel}
        placeholder={placeholder}
        value={value}
        onFocus={onFocus}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <CatalogSelect
      value={value}
      options={options}
      ariaLabel={ariaLabel}
      muted={muted}
      onFocus={onFocus}
      onChange={onChange}
    />
  );
}

function ticks(duration: number) {
  const step = duration <= 10 ? 1 : duration <= 30 ? 2 : duration <= 60 ? 5 : 10;
  const out: number[] = [0];
  for (let t = step; t < duration - step / 4; t += step) out.push(t);
  out.push(duration);
  return out;
}

interface Props {
  duration: number;
  segments: AnnotationSegment[];
  selectedId: string | null;
  currentTime: number;
  actionTypes?: string[];
  objectLabels?: string[];
  onSelect: (id: string) => void;
  onSeek: (t: number) => void;
  onChange: (id: string, start: number, end: number, keyframe: number) => void;
  onMeta: (id: string, patch: { action?: string; object?: string | null }) => void;
  onAdd: () => void;
  onRemove: (id: string) => void;
  onDragStart?: () => void;
  onDragEnd?: () => void;
}

export default function Timeline({
  duration,
  segments,
  selectedId,
  currentTime,
  onSelect,
  onSeek,
  onChange,
  onMeta,
  onAdd,
  onRemove,
  onDragStart,
  onDragEnd,
  actionTypes = [],
  objectLabels = [],
}: Props) {
  const dur = duration > 0 ? duration : 1;
  const playhead = Math.min(100, Math.max(0, (currentTime / dur) * 100));

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-1 flex">
        <div className="flex w-80 shrink-0 gap-1.5 px-3">
          <span className="min-w-0 flex-1 text-xs text-[var(--color-muted)]">action type</span>
          <span className="min-w-0 flex-1 text-xs text-[var(--color-muted)]">object</span>
        </div>
        <div className="flex min-w-0 flex-1 justify-between font-mono text-[10px] text-[var(--color-tertiary)]">
          {ticks(dur).map((t) => (
            <span key={t}>{t.toFixed(0)}s</span>
          ))}
        </div>
        <div className="w-24 shrink-0" />
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="flex gap-2">
          <div className="w-80 shrink-0 space-y-1.5">
            {segments.map((seg, i) => {
              const on = seg.id === selectedId;
              const color = colorFor(i);
              return (
                <div
                  key={seg.id}
                  className="flex h-8 min-w-0 items-center gap-1.5 rounded px-3"
                  style={{
                    background: on ? `${color}1A` : "var(--color-raised)",
                    borderTop: on ? "2px solid var(--color-accent)" : "1px solid var(--color-line)",
                    borderRight: on ? "2px solid var(--color-accent)" : "1px solid var(--color-line)",
                    borderBottom: on ? "2px solid var(--color-accent)" : "1px solid var(--color-line)",
                    borderLeft: `3px solid ${color}`,
                  }}
                  onClick={() => onSelect(seg.id)}
                >
                  <LabelField
                    className="field mt-0 h-6 min-w-0 flex-1 border-0 bg-transparent px-0 py-0 text-xs"
                    ariaLabel="action type"
                    placeholder="action type"
                    value={seg.action}
                    options={actionTypes}
                    onFocus={() => onSelect(seg.id)}
                    onChange={(v) => onMeta(seg.id, { action: v })}
                  />
                  <LabelField
                    className="field mt-0 h-6 min-w-0 flex-1 border-0 bg-transparent px-0 py-0 text-xs text-[var(--color-tertiary)]"
                    ariaLabel="object"
                    placeholder="object"
                    value={seg.object ?? ""}
                    options={objectLabels}
                    onFocus={() => onSelect(seg.id)}
                    muted
                    onChange={(v) => onMeta(seg.id, { object: v.trim() ? v : null })}
                  />
                </div>
              );
            })}
          </div>
          <div className="relative min-w-0 flex-1 space-y-1.5">
            {segments.map((seg, i) => (
              <RangeSlider
                key={seg.id}
                max={dur}
                start={seg.start}
                end={seg.end}
                keyframe={seg.keyframe}
                color={colorFor(i)}
                selected={seg.id === selectedId}
                onSelect={() => onSelect(seg.id)}
                onSeek={onSeek}
                onDragStart={onDragStart}
                onDragEnd={onDragEnd}
                onChange={(start, end, keyframe) => onChange(seg.id, start, end, keyframe)}
              />
            ))}
            {segments.length > 0 && (
              <div
                className="pointer-events-none absolute top-0 bottom-0 z-[2]"
                style={{ left: `${playhead}%` }}
              >
                <div className="absolute top-0 left-1/2 h-full w-px -translate-x-1/2 bg-[var(--color-accent)]" />
                <div className="absolute -top-1 left-1/2 -translate-x-1/2 border-x-4 border-t-[6px] border-x-transparent border-t-[var(--color-accent)]" />
              </div>
            )}
          </div>
          <div className="w-24 shrink-0 space-y-1.5">
            {segments.map((seg) => (
              <div key={seg.id} className="flex h-8 items-center justify-end gap-1">
                <span className="font-mono text-[10px] text-[var(--color-muted)]">
                  {seg.end - seg.start < 0.05
                    ? "—"
                    : `${seg.start.toFixed(1)}–${seg.end.toFixed(1)}`}
                </span>
                <button
                  type="button"
                  className="border-0 bg-transparent px-1.5 py-0.5 text-[12px] leading-none text-[var(--color-tertiary)] hover:text-[var(--color-bad)]"
                  aria-label={seg.end - seg.start < 0.05 ? "Delete action" : "Clear range"}
                  title={seg.end - seg.start < 0.05 ? "Delete action" : "Clear range"}
                  onClick={() => {
                    if (seg.end - seg.start < 0.05) onRemove(seg.id);
                    else onChange(seg.id, 0, 0, 0);
                  }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
      <button
        type="button"
        className="btn btn-ghost mt-2 w-full shrink-0 py-1.5 text-sm"
        disabled={duration <= 0}
        onClick={onAdd}
      >
        + Add action
      </button>
    </div>
  );
}
