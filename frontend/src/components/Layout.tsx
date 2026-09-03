import { Link, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen flex-col bg-[var(--color-ink)]">
      <header className="flex shrink-0 items-center justify-between border-b border-[var(--color-line)] bg-[var(--color-panel)] px-5 py-3">
        <Link to="/projects" className="flex items-center gap-2.5 no-underline">
          <span className="inline-flex h-3.5 gap-[3px]" aria-hidden>
            <span className="inline-block h-full w-1.5 rounded-sm bg-[var(--color-accent)]" />
            <span className="inline-block h-full w-1.5 rounded-sm bg-[var(--color-accent)]" />
          </span>
          <span className="text-sm font-semibold text-[var(--color-text)]">Boundr</span>
        </Link>
        <div className="flex items-center gap-3 text-sm text-[var(--color-muted)]">
          <span>{user?.name}</span>
          <button
            className="btn btn-ghost py-1"
            onClick={() => {
              logout();
              navigate("/login");
            }}
          >
            Log out
          </button>
        </div>
      </header>
      <main className="flex min-h-0 flex-1 flex-col">
        <Outlet />
      </main>
    </div>
  );
}
