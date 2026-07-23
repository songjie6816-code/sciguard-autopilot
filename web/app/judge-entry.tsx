import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { CommandCenter } from "./CommandCenter";
import "./globals.css";

const root = document.getElementById("root");
if (!root) throw new Error("Judge Mode root element is missing");

createRoot(root).render(
  <StrictMode>
    <CommandCenter judgeMode />
  </StrictMode>,
);
