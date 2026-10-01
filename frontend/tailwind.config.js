/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#ECEEE8",
        ink: "#161B18",
        graphite: "#565F5A",
        line: "#CCD1C7",
        panel: "#FFFFFF",
        signal: {
          DEFAULT: "#1F6B62",
          light: "#2C8C80",
          dark: "#154A44",
        },
        gold: "#B08A2E",
        alert: "#B23B3B",
      },
      fontFamily: {
        display: ["\"Space Grotesk\"", "system-ui", "sans-serif"],
        body: ["\"Inter\"", "system-ui", "sans-serif"],
        mono: ["\"IBM Plex Mono\"", "ui-monospace", "monospace"],
      },
      borderRadius: {
        sm: "3px",
        DEFAULT: "5px",
      },
    },
  },
  plugins: [],
};
