module.exports = {
  darkMode: ["class", '[data-theme="koala-dark"]'],
  content: [],
  safelist: [
    'alert-success',
    'alert-info',
    'alert-error',
    'alert-warning',
    'bg-error/10',
    'bg-success/10',
  ],
  theme: {
    extend: {
      aspectRatio: {
        '3/2': '3 / 2',
      },
    },
    container: {
      center: true,
    },
  },
  variants: {
    extend: {},
  },
  plugins: [],
}
