/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        stellar: { 50:'#f0f4ff',100:'#dbe4ff',200:'#bac8ff',300:'#91a7ff',400:'#748ffc',500:'#5c7cfa',600:'#4c6ef5',700:'#4263eb',800:'#3b5bdb',900:'#364fc7' },
        k8s: { 50:'#e3f2fd',100:'#bbdefb',200:'#90caf9',300:'#64b5f6',400:'#42a5f5',500:'#326ce5',600:'#1e88e5',700:'#1976d2',800:'#1565c0',900:'#0d47a1' }
      },
      animation: { 'pulse-slow':'pulse 3s cubic-bezier(0.4,0,0.6,1) infinite', shimmer:'shimmer 2s linear infinite' },
      keyframes: { shimmer: { '0%':{ backgroundPosition:'-200% 0' }, '100%':{ backgroundPosition:'200% 0' } } }
    },
  },
  plugins: [],
}
