import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#f6f4ef",
        card: "#fffefb",
        ink: { DEFAULT: "#1d2521", soft: "#4a554f", faint: "#7b867f" },
        rule: "#dcd8cd",
        ledger: { DEFAULT: "#1f5c47", dark: "#174536", soft: "#e4efe9" },
        pass: { DEFAULT: "#1f7a4d", soft: "#e2f1e8" },
        warn: { DEFAULT: "#9a6a00", soft: "#fbf0d4" },
        fail: { DEFAULT: "#b3372b", soft: "#f9e3e0" },
        info: { DEFAULT: "#2b5f8f", soft: "#e3edf6" },
      },
      fontFamily: {
        sans: ['ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', 'sans-serif'],
        mono: ['ui-monospace', '"SF Mono"', 'Menlo', 'Consolas', '"Liberation Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
};

export default config;