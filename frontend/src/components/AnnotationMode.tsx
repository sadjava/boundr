export default function AnnotationMode({
  withAnnotations,
  onChange,
  disabled,
}: {
  withAnnotations: boolean;
  onChange: (withAnnotations: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <button
        type="button"
        className={`btn ${withAnnotations ? "btn-ghost" : "btn-primary"}`}
        disabled={disabled}
        onClick={() => onChange(false)}
      >
        Videos only
      </button>
      <button
        type="button"
        className={`btn ${withAnnotations ? "btn-primary" : "btn-ghost"}`}
        disabled={disabled}
        onClick={() => onChange(true)}
      >
        With annotations
      </button>
    </div>
  );
}
