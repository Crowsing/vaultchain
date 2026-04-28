import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { initSentry } from "./lib/sentry";
import "./index.css";

initSentry();

const themeQuery = window.matchMedia("(prefers-color-scheme: dark)");
const applyTheme = (e: MediaQueryList | MediaQueryListEvent) => {
  document.documentElement.dataset.theme = e.matches ? "dark" : "light";
};
applyTheme(themeQuery);
themeQuery.addEventListener("change", applyTheme);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
