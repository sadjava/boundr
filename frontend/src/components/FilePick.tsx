import { useEffect, useRef, useState } from "react";

export default function FilePick({
  accept,
  file,
  onFile,
  disabled,
}: {
  accept: string;
  file: File | null;
  onFile: (file: File | null) => void;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!file) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);

  return (
    <div className="flex flex-wrap items-center gap-3">
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        disabled={disabled}
        onChange={(e) => {
          onFile(e.target.files?.[0] ?? null);
          e.target.value = "";
        }}
      />
      <button
        type="button"
        className="btn btn-ghost"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        Browse
      </button>
      {file && url && (
        <a
          href={url}
          download={file.name}
          className="text-sm font-medium text-[var(--color-accent)] no-underline hover:underline"
        >
          {file.name}
        </a>
      )}
    </div>
  );
}
