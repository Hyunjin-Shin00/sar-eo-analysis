/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:      '#1A1D23',
        panel:   '#21252D',
        surface: '#282C35',
        border:  '#333844',
        dim:     '#7A8499',
        accent:  '#4A9EFF',
        green:   '#3ECF72',
        amber:   '#F5A623',
        danger:  '#F56565',
      },
    },
  },
}
