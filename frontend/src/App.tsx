import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Models from "./pages/Models";
import ProjectCreate from "./pages/ProjectCreate";
import ProjectDetail from "./pages/ProjectDetail";
import ProjectImport from "./pages/ProjectImport";
import Projects from "./pages/Projects";
import TaskCreate from "./pages/TaskCreate";
import TaskDetail from "./pages/TaskDetail";
import TaskImport from "./pages/TaskImport";
import VideoPage from "./pages/VideoPage";

function Guard({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return <div className="p-10 text-[var(--color-muted)]">Loading…</div>;
  }
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <Guard>
            <Layout />
          </Guard>
        }
      >
        <Route path="/projects" element={<Projects />} />
        <Route path="/models" element={<Models />} />
        <Route path="/projects/new" element={<ProjectCreate />} />
        <Route path="/projects/:id/tasks/new" element={<TaskCreate />} />
        <Route path="/projects/:id/import" element={<ProjectImport />} />
        <Route path="/projects/:id" element={<ProjectDetail />} />
        <Route path="/tasks/:id/import" element={<TaskImport />} />
        <Route path="/tasks/:id" element={<TaskDetail />} />
        <Route path="/videos/:id" element={<VideoPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  );
}
