/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: { sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'], mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'] },
      colors: {
        ink: { DEFAULT: '#0F1B2D', 700: '#1B2A41', 600: '#2A3B55', 400: '#6B7A90', 300: '#9AA7B8', 200: '#C9D3E3' },
        paper: { DEFAULT: '#F5F6F8', card: '#FFFFFF', rule: '#E2E6EC', tint: '#EEF1F5' },
        ok: { DEFAULT: '#0E7C66', soft: '#E3F3EF' },
        warn: { DEFAULT: '#A86A0B', soft: '#FBF0DC' },
        bad: { DEFAULT: '#B42318', soft: '#FCE8E6' },
        info: { DEFAULT: '#2457C5', soft: '#E6EDFB' },
      },
    },
  },
  plugins: [],
}
