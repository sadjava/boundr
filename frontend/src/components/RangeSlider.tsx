import { useRef, useState, type PointerEvent } from "react";

function clamp(n: number, a: number, b: number) {
  return Math.min(b, Math.max(a, n));
}

type Kind = "start" | "end" | "draw" | "keyframe";

interface Props {
  min?: number;
  max: number;
  start: number;
  end: number;
  keyframe: number;
  color: string;
  selected?: boolean;
  onChange: (start: number, end: number, keyframe: number) => void;
  onSelect?: () => void;
  onSeek?: (t: number) => void;
  onDragStart?: () => void;
  onDragEnd?: () => void;
}

export default function RangeSlider({
  min = 0,
  max,
  start,
  end,
  keyframe,
  color,
  selected,
  onChange,
  onSelect,
  onSeek,
  onDragStart,
  onDragEnd,
}: Props) {
  const trackRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ kind: Kind; origin: number; start: number; end: number; keyframe: number } | null>(
    null,
  );
  const [live, setLive] = useState<{ start: number; end: number; keyframe: number } | null>(null);
  const [drawing, setDrawing] = useState(false);
  const span = Math.max(max - min, 0.001);
  const gap = Math.max(0.05, span * 0.004);
  const startRef = useRef(start);
  const endRef = useRef(end);
  const kfRef = useRef(keyframe);
  if (!live) {
    startRef.current = start;
    endRef.current = end;
    kfRef.current = keyframe;
  }

  const s = live?.start ?? start;
  const e = live?.end ?? end;
  const kf = live?.keyframe ?? keyframe;
  const empty = e - s < gap && !drawing;

  function clientToValue(clientX: number) {
    const rect = trackRef.current!.getBoundingClientRect();
    const t = clamp((clientX - rect.left) / rect.width, 0, 1);
    return min + t * span;
  }

  function commitLive(ns: number, ne: number, nkf: number) {
    startRef.current = ns;
    endRef.current = ne;
    kfRef.current = nkf;
    setLive({ start: ns, end: ne, keyframe: nkf });
  }

  function apply(kind: Kind, clientX: number) {
    const raw = clientToValue(clientX);
    let ns = startRef.current;
    let ne = endRef.current;
    let nkf = kfRef.current;
    if (kind === "start") {
      ns = clamp(raw, min, ne - gap);
      nkf = clamp(nkf, ns, ne);
      onSeek?.(ns);
    } else if (kind === "end") {
      ne = clamp(raw, ns + gap, max);
      nkf = clamp(nkf, ns, ne);
      onSeek?.(ne);
    } else if (kind === "keyframe") {
      nkf = clamp(raw, ns, ne);
      onSeek?.(nkf);
    } else {
      const origin = drag.current?.origin ?? raw;
      ns = clamp(Math.min(origin, raw), min, max);
      ne = clamp(Math.max(origin, raw), min, max);
      nkf = (ns + ne) / 2;
      onSeek?.(raw);
    }
    commitLive(ns, ne, nkf);
  }

  function bind(kind: Kind) {
    return {
      onPointerDown: (e: PointerEvent<HTMLElement>) => {
        e.preventDefault();
        e.stopPropagation();
        e.currentTarget.setPointerCapture(e.pointerId);
        onDragStart?.();
        onSelect?.();
        if (kind === "draw") setDrawing(true);
        drag.current = {
          kind,
          origin: clientToValue(e.clientX),
          start: startRef.current,
          end: endRef.current,
          keyframe: kfRef.current,
        };
        apply(kind, e.clientX);
      },
      onPointerMove: (e: PointerEvent<HTMLElement>) => {
        e.stopPropagation();
        if (!e.currentTarget.hasPointerCapture(e.pointerId) || !drag.current) return;
        apply(drag.current.kind, e.clientX);
      },
      onPointerUp: (e: PointerEvent<HTMLElement>) => {
        e.stopPropagation();
        const d = drag.current;
        drag.current = null;
        setDrawing(false);
        if (d?.kind === "draw") {
          const ns = startRef.current;
          const ne = endRef.current;
          if (ne - ns < gap) {
            startRef.current = 0;
            endRef.current = 0;
            kfRef.current = 0;
            onChange(0, 0, 0);
          } else {
            const mid = (ns + ne) / 2;
            kfRef.current = mid;
            onChange(ns, ne, mid);
          }
        } else if (d) {
          onChange(startRef.current, endRef.current, kfRef.current);
        }
        setLive(null);
        onDragEnd?.();
      },
      onPointerCancel: () => {
        drag.current = null;
        setDrawing(false);
        setLive(null);
        onDragEnd?.();
      },
    };
  }

  const left = ((s - min) / span) * 100;
  const width = Math.max(((e - s) / span) * 100, drawing ? 0.2 : 0);
  const kfLeft = ((kf - min) / span) * 100;
  const showHandles = !empty && !drawing;

  return (
    <div
      ref={trackRef}
      className="relative h-8 flex-1 touch-none rounded-[3px]"
      style={{
        background: "var(--color-raised)",
        outline: selected ? "2px solid var(--color-accent)" : "1px solid var(--color-line)",
        cursor: empty || drawing ? "crosshair" : "pointer",
      }}
      {...(empty || drawing
        ? bind("draw")
        : {
            onPointerDown: (e: PointerEvent<HTMLDivElement>) => {
              if (e.target !== trackRef.current) return;
              onSelect?.();
              onSeek?.(clientToValue(e.clientX));
            },
          })}
    >
      {empty ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center font-mono text-[10px] text-[var(--color-tertiary)]">
          drag to set range
        </div>
      ) : (
        <div
          className="pointer-events-none absolute top-0.5 bottom-0.5 z-0 rounded-[3px]"
          style={{
            left: `${left}%`,
            width: `${width}%`,
            background: `${color}${selected ? "B3" : "66"}`,
            border: `1.5px solid ${color}`,
          }}
        />
      )}
      {showHandles && (
        <>
          <button
            type="button"
            aria-label="Start time"
            className="absolute top-0 bottom-0 z-[1] w-5 -translate-x-1/2 cursor-ew-resize border-0 bg-transparent p-0"
            style={{ left: `${left}%` }}
            {...bind("start")}
          >
            <span className="pointer-events-none absolute top-0 bottom-0 left-1/2 w-1 -translate-x-1/2 bg-[var(--color-text)]" />
          </button>
          <button
            type="button"
            aria-label="End time"
            className="absolute top-0 bottom-0 z-[1] w-5 -translate-x-1/2 cursor-ew-resize border-0 bg-transparent p-0"
            style={{ left: `${left + width}%` }}
            {...bind("end")}
          >
            <span className="pointer-events-none absolute top-0 bottom-0 left-1/2 w-1 -translate-x-1/2 bg-[var(--color-text)]" />
          </button>
          <button
            type="button"
            aria-label="Keyframe"
            className="absolute top-1/2 z-[3] flex h-4 w-4 -translate-x-1/2 -translate-y-1/2 cursor-grab items-center justify-center border-0 bg-transparent p-0"
            style={{ left: `${kfLeft}%` }}
            {...bind("keyframe")}
          >
            <span
              className="pointer-events-none block h-2 w-2 rotate-45"
              style={{ background: color, border: "1px solid var(--color-text)" }}
            />
          </button>
        </>
      )}
    </div>
  );
}
