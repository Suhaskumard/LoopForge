import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import { AuthProvider } from "./auth";
import { initTheme } from "./theme";
import "./styles.css";
import "./theme.css";
import "./motion.css";
import "./polish.css";
import "./live.css";
import "./create.css";
import "./pages.css";
import "./features.css";
import "./intel.css";
import "./advanced.css";

initTheme();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
