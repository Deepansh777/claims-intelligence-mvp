// Entry of the offline dashboard viewer (npm run build:dashboard); the backend inlines the
// built script and styles next to the data snapshot in each exported HTML file.
import ReactDOM from "react-dom/client";
import { ThemeProvider } from "@mui/material/styles";
import { theme } from "../lib/theme";
import type { DashboardPayload } from "../lib/types";
import { CellTooltip } from "../components/CellTooltip";
import { DashboardDocument } from "./DashboardDocument";
import "../styles/tokens.css";
import "../styles/components.css";
import "../styles/chat.css";
import "../styles/ask.css";
import "../styles/dashboard.css";

const data = JSON.parse(document.getElementById("dashboard-data")!.textContent!) as DashboardPayload;
ReactDOM.createRoot(document.getElementById("root")!).render(
  <ThemeProvider theme={theme}>
    <DashboardDocument dashboard={data} />
    <CellTooltip />
  </ThemeProvider>,
);
