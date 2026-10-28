/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    // system font stack only: the demo must run offline (TR-04)
    fontFamily: {
      sans: ['system-ui', '"Segoe UI"', "Roboto", "Helvetica", "Arial", "sans-serif"],
      mono: ["ui-monospace", "Consolas", "Menlo", "monospace"],
    },
    extend: {},
  },
  plugins: [],
};
