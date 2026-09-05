export type SortField = "created" | "updated";
export type SortDir = "desc" | "asc";

export type SortState = { field: SortField; dir: SortDir };

export function sortByDates<T extends { created_at: string; updated_at: string }>(
  items: T[],
  sort: SortState,
): T[] {
  const copy = [...items];
  const key = sort.field === "created" ? "created_at" : "updated_at";
  copy.sort((a, b) => {
    const cmp = a[key].localeCompare(b[key]);
    return sort.dir === "asc" ? cmp : -cmp;
  });
  return copy;
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
  function pickField(field: SortField) {
    if (sort.field === field) return;
    onSort({ field, dir: "desc" });
  }

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
        <span className="text-sm text-[var(--color-muted)]">Sort</span>
        <button
          type="button"
          className={`btn ${sort.field === "created" ? "btn-primary" : "btn-ghost"}`}
          onClick={() => pickField("created")}
        >
          Created
        </button>
        <button
          type="button"
          className={`btn ${sort.field === "updated" ? "btn-primary" : "btn-ghost"}`}
          onClick={() => pickField("updated")}
        >
          Updated
        </button>
        <button
          type="button"
          className="btn btn-ghost px-2.5"
          aria-label={sort.dir === "desc" ? "Descending" : "Ascending"}
          title={sort.dir === "desc" ? "Newest first" : "Oldest first"}
          onClick={() => onSort({ ...sort, dir: sort.dir === "desc" ? "asc" : "desc" })}
        >
          {sort.dir === "desc" ? "↓" : "↑"}
        </button>
      </div>
    </div>
  );
}
