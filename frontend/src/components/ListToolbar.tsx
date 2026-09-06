export type SortField = "name" | "created" | "updated";
export type SortDir = "desc" | "asc";

export type SortState = { field: SortField; dir: SortDir };

const FIELDS: { id: SortField; label: string }[] = [
  { id: "name", label: "Name" },
  { id: "created", label: "Created" },
  { id: "updated", label: "Updated" },
];

export function sortItems<T extends { name: string; created_at: string; updated_at: string }>(
  items: T[],
  sort: SortState,
): T[] {
  const key = sort.field === "name" ? "name" : sort.field === "created" ? "created_at" : "updated_at";
  const copy = [...items];
  copy.sort((a, b) => {
    const cmp = a[key].localeCompare(b[key], undefined, { sensitivity: "base" });
    return sort.dir === "asc" ? cmp : -cmp;
  });
  return copy;
}

function dirTitle(sort: SortState) {
  if (sort.field === "name") return sort.dir === "asc" ? "A–Z" : "Z–A";
  return sort.dir === "desc" ? "Newest first" : "Oldest first";
}

export default function ListToolbar({
  query,
  onQuery,
  sort,
  onSort,
  placeholder = "Name",
}: {
  query: string;
  onQuery: (q: string) => void;
  sort: SortState;
  onSort: (next: SortState) => void;
  placeholder?: string;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end gap-3">
      <label className="min-w-48 flex-1 block text-sm">
        Search
        <input
          className="field"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder={placeholder}
        />
      </label>
      <div className="flex flex-wrap items-center gap-2 pb-0.5">
        <label className="flex items-center gap-2 text-sm text-[var(--color-muted)]">
          Sort
          <select
            className="field mt-0 w-32"
            aria-label="Sort by"
            value={sort.field}
            onChange={(e) => {
              const field = e.target.value as SortField;
              onSort({ field, dir: field === "name" ? "asc" : "desc" });
            }}
          >
            {FIELDS.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="btn btn-ghost px-2.5"
          aria-label={sort.dir === "desc" ? "Descending" : "Ascending"}
          title={dirTitle(sort)}
          onClick={() => onSort({ ...sort, dir: sort.dir === "desc" ? "asc" : "desc" })}
        >
          {sort.dir === "desc" ? "↓" : "↑"}
        </button>
      </div>
    </div>
  );
}
