import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        background: "#0a0d14",
        surface: {
          50: "#182030",
          100: "#131a27",
          200: "#0e1420",
          DEFAULT: "#131a27",
        },
        border: {
          subtle: "#1e293b",
          muted: "#334155",
          DEFAULT: "#1e293b",
        },
        terminal: {
          green: "#10b981", // Bullish / Long / Profit
          red: "#ef4444",   // Bearish / Short / Loss
          cyan: "#06b6d4",  // EMA9 / Agent info
          amber: "#f59e0b", // Warning / Hold / Regime
          purple: "#8b5cf6",// MACD / Secondary
          blue: "#3b82f6",  // Selection / Active
        },
      },
      fontFamily: {
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};

export default config;
