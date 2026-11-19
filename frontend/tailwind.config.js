/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        vlute: {
          green: "#00703c",
          dark: "#005a30",
          accent: "#00a65a",
          emerald: "#008d4c",
          orange: "#e67e22",
          blue: "#0073b7",
          charcoal: "#222d32",
          charcoalCard: "#1e282c",
        },
      },
    },
  },
  plugins: [],
};
