import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";

function navClass({ isActive }: { isActive: boolean }) {
  return [
    "rounded-md px-4 py-2 text-base font-semibold no-underline transition-colors",
    isActive
      ? "bg-[var(--color-raised)] text-[var(--color-text)]"
      : "text-[var(--color-muted)] hover:bg-[var(--color-raised)] hover:text-[var(--color-text)]",
  ].join(" ");
}

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
        <div className="flex items-center gap-6 text-sm text-[var(--color-muted)]">
          <nav className="flex items-center gap-5" aria-label="Main">
            <NavLink to="/models" className={navClass}>
              Models
            </NavLink>
            <NavLink to="/projects" className={navClass} end>
              Projects
            </NavLink>
          </nav>
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
