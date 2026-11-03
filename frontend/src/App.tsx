import { useQuery } from "@tanstack/react-query";
import { Box, Chip, Container, Paper, Typography } from "@mui/material";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiGet } from "./lib/apiClient";

type Health = { status: string; database: string };

// Placeholder data — replaced by real analysis results later.
const sampleData = [
  { month: "May", pmpm: 412 },
  { month: "Jun", pmpm: 438 },
  { month: "Jul", pmpm: 401 },
  { month: "Aug", pmpm: 465 },
];

export default function App() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["health"],
    queryFn: () => apiGet<Health>("/health"),
  });

  const backendStatus = isLoading
    ? "checking…"
    : isError
      ? "unreachable"
      : `${data?.status} (db: ${data?.database})`;

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Typography variant="h4" gutterBottom>
        Claims Intelligence Platform
      </Typography>

      <Box sx={{ mb: 3 }}>
        <Chip
          label={`Backend: ${backendStatus}`}
          color={isError ? "error" : isLoading ? "default" : "success"}
        />
      </Box>

      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" gutterBottom>
          Sample PMPM trend
        </Typography>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={sampleData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" />
            <YAxis />
            <Tooltip />
            <Bar dataKey="pmpm" fill="#1976d2" />
          </BarChart>
        </ResponsiveContainer>
      </Paper>
    </Container>
  );
}
