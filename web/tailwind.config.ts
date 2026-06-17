import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["var(--font-display)"],
        body: ["var(--font-body)"],
        mono: ["var(--font-mono)"]
      },
      colors: {
        void: "var(--void)",
        abyss: "var(--abyss)",
        text: "var(--text)",
        muted: "var(--muted)"
      }
    }
  },
  plugins: []
} satisfies Config;
