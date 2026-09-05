const TOKEN_KEY = "vtas_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return (await res.json()) as T;
  return res as unknown as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  postForm: <T>(path: string, body: FormData) => request<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  delete: (path: string) => request<void>(path, { method: "DELETE" }),
};

async function downloadBlob(path: string, filename: string) {
  const token = getToken();
  const res = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function downloadExport(videoId: string, format: "json" | "csv", filename: string) {
  await downloadBlob(`/api/videos/${videoId}/export?format=${format}`, filename);
}

function formatsQuery(formats: { json: boolean; csv: boolean }) {
  const parts: string[] = [];
  if (formats.json) parts.push("json");
  if (formats.csv) parts.push("csv");
  return parts.join(",") || "json";
}

export async function downloadTaskExport(
  taskId: string,
  includeVideos: boolean,
  formats: { json: boolean; csv: boolean },
  filename: string,
) {
  await downloadBlob(
    `/api/tasks/${taskId}/export?include_videos=${includeVideos}&formats=${formatsQuery(formats)}`,
    filename,
  );
}

export async function downloadProjectExport(
  projectId: string,
  includeVideos: boolean,
  formats: { json: boolean; csv: boolean },
  filename: string,
) {
  await downloadBlob(
    `/api/projects/${projectId}/export?include_videos=${includeVideos}&formats=${formatsQuery(formats)}`,
    filename,
  );
}
