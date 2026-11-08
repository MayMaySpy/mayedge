import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { startDesk } from "./lib/startup";
import "./index.css";

// The selected Market's candles go out before React renders; the rest waits for them.
startDesk();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
