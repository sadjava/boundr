import { useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
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

const ROW = 38;

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
  onReorder?: (id: string, toIndex: number) => void;
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
  onReorder,
  onDragStart,
  onDragEnd,
  actionTypes = [],
  objectLabels = [],
}: Props) {
  const dur = duration > 0 ? duration : 1;
  const playhead = Math.min(100, Math.max(0, (currentTime / dur) * 100));
  const wrapRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const dragId = useRef<string | null>(null);
  const dropAtRef = useRef<number | null>(null);
  const grabX = useRef(0);
  const grabY = useRef(0);
  const [dropAt, setDropAt] = useState<number | null>(null);
  const [ghost, setGhost] = useState<{
    id: string;
    x: number;
    y: number;
    w: number;
    action: string;
    object: string | null;
    color: string;
    start: number;
    end: number;
  } | null>(null);

  function setDrop(n: number | null) {
    dropAtRef.current = n;
    setDropAt(n);
  }

  function indexAtY(y: number) {
    const root = listRef.current;
    if (!root) return 0;
    const max = Math.max(0, segments.length - (dragId.current ? 1 : 0));
    const top = root.getBoundingClientRect().top;
    return Math.max(0, Math.min(max, Math.round((y - top - 16) / ROW)));
  }

  function beginReorder(e: ReactPointerEvent<HTMLElement>, id: string) {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const i = segments.findIndex((s) => s.id === id);
    const row = listRef.current?.children[i] as HTMLElement | undefined;
    const wrap = wrapRef.current;
    if (!row || !wrap || i < 0) return;
    const rr = row.getBoundingClientRect();
    const wr = wrap.getBoundingClientRect();
    grabX.current = e.clientX - wr.left;
    grabY.current = e.clientY - rr.top;
    const seg = segments[i];
    dragId.current = id;
    onSelect(id);
    setDrop(i);
    setGhost({
      id,
      x: wr.left,
      y: rr.top,
      w: wr.width,
      action: seg.action,
      object: seg.object,
      color: colorFor(i),
      start: seg.start,
      end: seg.end,
    });
    const move = (ev: PointerEvent) => {
      setGhost((g) =>
        g ? { ...g, x: ev.clientX - grabX.current, y: ev.clientY - grabY.current } : g,
      );
      setDrop(indexAtY(ev.clientY));
    };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
      const sid = dragId.current;
      const to = dropAtRef.current;
      dragId.current = null;
      setGhost(null);
      setDrop(null);
      if (sid != null && to != null) onReorder?.(sid, to);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", up);
  }

  const shown = ghost ? segments.filter((s) => s.id !== ghost.id) : segments;
  const hole = ghost && dropAt != null ? dropAt : null;
  function shift(j: number): CSSProperties | undefined {
    if (hole == null) return undefined;
    return {
      transform: `translateY(${j >= hole ? ROW : 0}px)`,
      transition: "transform 80ms ease",
    };
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-1 flex">
        <div className="flex w-80 shrink-0 gap-1.5 px-3">
          <span className="min-w-0 flex-1 text-xs text-[var(--color-muted)]">action type</span>
          <span className="min-w-0 flex-1 text-xs text-[var(--color-muted)]">object</span>
        </div>
        <div
          className="relative flex min-w-0 flex-1 cursor-ew-resize touch-none justify-between font-mono text-[10px] text-[var(--color-tertiary)]"
          onPointerDown={(e) => {
            if (e.button !== 0) return;
            e.currentTarget.setPointerCapture(e.pointerId);
            onDragStart?.();
            const rect = e.currentTarget.getBoundingClientRect();
            const t = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
            onSeek(t * dur);
          }}
          onPointerMove={(e) => {
            if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
            const rect = e.currentTarget.getBoundingClientRect();
            const t = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
            onSeek(t * dur);
          }}
          onPointerUp={(e) => {
            if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
            onDragEnd?.();
          }}
        >
          {ticks(dur).map((t) => (
            <span key={t}>{t.toFixed(0)}s</span>
          ))}
        </div>
        <div className="w-24 shrink-0" />
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <div ref={wrapRef} className="flex gap-2">
          <div
            ref={listRef}
            className="relative w-80 shrink-0 space-y-1.5"
            style={{ paddingBottom: ghost ? ROW : undefined }}
          >
            {hole != null && (
              <div
                className="pointer-events-none absolute right-0 left-0 h-8 rounded border border-dashed border-[var(--color-accent)]"
                style={{ top: hole * ROW }}
              />
            )}
            {shown.map((seg, j) => {
              const orig = segments.findIndex((s) => s.id === seg.id);
              const on = seg.id === selectedId;
              const color = colorFor(orig);
              return (
                <div
                  key={seg.id}
                  className="flex h-8 min-w-0 items-center gap-1 rounded px-2"
                  style={{
                    background: on ? `${color}1A` : "var(--color-raised)",
                    border: on ? "2px solid var(--color-accent)" : "1px solid var(--color-line)",
                    borderLeft: `3px solid ${color}`,
                    ...shift(j),
                  }}
                  onClick={() => onSelect(seg.id)}
                >
                  <button
                    type="button"
                    className="tl-grip"
                    aria-label="Drag to reorder"
                    title="Drag to reorder"
                    onPointerDown={(e) => beginReorder(e, seg.id)}
                  />
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
          <div className="relative min-w-0 flex-1">
            <div
              className="relative z-0 space-y-1.5"
              style={{ paddingBottom: ghost ? ROW : undefined }}
            >
              {hole != null && (
                <div
                  className="pointer-events-none absolute right-0 left-0 h-8 rounded border border-dashed border-[var(--color-accent)]"
                  style={{ top: hole * ROW }}
                />
              )}
              {shown.map((seg, j) => {
                const orig = segments.findIndex((s) => s.id === seg.id);
                return (
                  <div key={seg.id} style={shift(j)}>
                    <RangeSlider
                      max={dur}
                      start={seg.start}
                      end={seg.end}
                      keyframe={seg.keyframe}
                      color={colorFor(orig)}
                      selected={seg.id === selectedId}
                      onSelect={() => onSelect(seg.id)}
                      onSeek={onSeek}
                      onDragStart={onDragStart}
                      onDragEnd={onDragEnd}
                      onChange={(start, end, keyframe) => onChange(seg.id, start, end, keyframe)}
                    />
                  </div>
                );
              })}
            </div>
            {segments.length > 0 && (
              <div
                className="pointer-events-none absolute inset-0 z-50"
                aria-hidden
              >
                <div
                  className="absolute top-0 bottom-0 w-0.5 -translate-x-1/2 bg-[var(--color-accent)]"
                  style={{ left: `${playhead}%` }}
                />
                <div
                  className="absolute -top-1 -translate-x-1/2 border-x-4 border-t-[6px] border-x-transparent border-t-[var(--color-accent)]"
                  style={{ left: `${playhead}%` }}
                />
              </div>
            )}
          </div>
          <div className="relative w-24 shrink-0 space-y-1.5" style={{ paddingBottom: ghost ? ROW : undefined }}>
            {hole != null && (
              <div
                className="pointer-events-none absolute right-0 left-0 h-8 rounded border border-dashed border-[var(--color-accent)]"
                style={{ top: hole * ROW }}
              />
            )}
            {shown.map((seg, j) => (
              <div key={seg.id} className="flex h-8 items-center justify-end gap-1" style={shift(j)}>
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
      {ghost && (
        <div
          className="tl-ghost"
          style={{ left: ghost.x, top: ghost.y, width: ghost.w }}
        >
          <div
            className="flex h-8 min-w-0 items-center gap-1 rounded px-2"
            style={{
              width: "20rem",
              background: `${ghost.color}1A`,
              border: "2px solid var(--color-accent)",
              borderLeft: `3px solid ${ghost.color}`,
            }}
          >
            <span className="tl-grip" />
            <span className="min-w-0 flex-1 truncate text-xs">{ghost.action || "untitled"}</span>
            <span className="min-w-0 flex-1 truncate text-xs text-[var(--color-tertiary)]">
              {ghost.object ?? "none"}
            </span>
          </div>
          <div
            className="relative h-8 min-w-0 flex-1 rounded-[3px]"
            style={{ background: "var(--color-raised)", outline: "2px solid var(--color-accent)" }}
          >
            {ghost.end - ghost.start >= 0.05 && (
              <div
                className="absolute top-0.5 bottom-0.5 rounded-[3px]"
                style={{
                  left: `${(ghost.start / dur) * 100}%`,
                  width: `${((ghost.end - ghost.start) / dur) * 100}%`,
                  background: `${ghost.color}B3`,
                  border: `1.5px solid ${ghost.color}`,
                }}
              />
            )}
          </div>
          <span className="w-24 shrink-0 text-right font-mono text-[10px] text-[var(--color-muted)]">
            {ghost.end - ghost.start < 0.05
              ? "—"
              : `${ghost.start.toFixed(1)}–${ghost.end.toFixed(1)}`}
          </span>
        </div>
      )}
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
