import { createTheme } from "@mui/material/styles";

// MUI controls in the house font and accent; sizes follow tokens.css.
export const theme = createTheme({
  typography: { fontFamily: '"Noto Sans", Arial, sans-serif', fontSize: 13 },
  palette: { primary: { main: "#2f9d90" } },
});
