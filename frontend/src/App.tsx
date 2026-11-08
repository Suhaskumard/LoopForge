import { Route, Routes, Navigate } from "react-router";
import { Protected } from "./components/Layout";
import { Admin } from "./pages/Admin";
import { Analytics } from "./pages/Analytics";
import { CodeWorkspace } from "./pages/CodeWorkspace";
import { CommandCenter } from "./pages/CommandCenter";
import { CreateTask } from "./pages/CreateTask";
import { Evaluation } from "./pages/Evaluation";
import { LiveWorkflow } from "./pages/LiveWorkflow";
import { Login } from "./pages/Login";
import { Report } from "./pages/Report";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected />}>
        <Route path="/" element={<CommandCenter />} />
        <Route path="/tasks/new" element={<CreateTask />} />
        <Route path="/tasks/:id" element={<LiveWorkflow />} />
        <Route path="/tasks/:id/code" element={<CodeWorkspace />} />
        <Route path="/tasks/:id/evaluation" element={<Evaluation />} />
        <Route path="/tasks/:id/report" element={<Report />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/admin" element={<Admin />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
