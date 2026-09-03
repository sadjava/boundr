import { FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function Login() {
  const { user, loading, login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loading && user) return <Navigate to="/projects" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "register") await register(name, email, password);
      else await login(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-md overflow-hidden rounded-lg border border-[var(--color-line)] bg-[var(--color-panel)]"
      >
        <div className="h-1 bg-[var(--color-accent)]" />
        <div className="p-8">
          <div className="mb-6">
            <div className="mb-3 flex items-center gap-2">
              <span className="inline-flex h-3.5 gap-[3px]" aria-hidden>
                <span className="inline-block h-full w-1.5 rounded-sm bg-[var(--color-accent)]" />
                <span className="inline-block h-full w-1.5 rounded-sm bg-[var(--color-accent)]" />
              </span>
              <span className="text-xs font-semibold text-[var(--color-muted)]">Boundr</span>
            </div>
            <h1 className="m-0 text-2xl font-semibold">
              {mode === "login" ? "Sign in" : "Create account"}
            </h1>
            <p className="mt-1 text-sm text-[var(--color-muted)]">
              Review action clips, edit the timeline, export labels.
            </p>
          </div>
          {mode === "register" && (
            <label className="mb-3 block text-sm">
              Name
              <input className="field" value={name} onChange={(e) => setName(e.target.value)} required />
            </label>
          )}
          <label className="mb-3 block text-sm">
            Email
            <input
              type="email"
              className="field"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label className="mb-4 block text-sm">
            Password
            <input
              type="password"
              className="field"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={6}
              required
            />
          </label>
          {error && <p className="mb-3 text-sm text-[var(--color-bad)]">{error}</p>}
          <button type="submit" disabled={busy} className="btn btn-primary w-full py-2.5">
            {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Register"}
          </button>
          <button
            type="button"
            className="mt-4 w-full cursor-pointer border-0 bg-transparent text-sm text-[var(--color-muted)]"
            onClick={() => setMode(mode === "login" ? "register" : "login")}
          >
            {mode === "login" ? "Need an account? Register" : "Have an account? Sign in"}
          </button>
        </div>
      </form>
    </div>
  );
}
