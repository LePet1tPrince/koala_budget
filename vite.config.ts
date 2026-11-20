import { defineConfig } from 'vite';
import path from 'path';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [
    react(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './assets/javascript'),
      // this may not be needed anymore, but leaving it shouldn't hurt
      'use-sync-external-store/shim': path.resolve(__dirname, './node_modules/use-sync-external-store/shim'),
    },
  },
  base: '/static/', // Should match Django's STATIC_URL
  build: {
    manifest: true, // The manifest.json file is needed for django-vite
    outDir: path.resolve(__dirname, './static'), // Output directory for production build
    emptyOutDir: false, // Preserve the outDir to not clobber Django's other files.
    rollupOptions: {
      input: {
        'site-base-css': path.resolve(__dirname, './assets/styles/site-base.css'),
        'site-tailwind-css': path.resolve(__dirname, './assets/styles/site-tailwind.css'),
        'fonts-css': path.resolve(__dirname, './assets/styles/fonts.css'),
        'site': path.resolve(__dirname, './assets/javascript/site.js'),
        'app': path.resolve(__dirname, './assets/javascript/app.js'),
        'teams': path.resolve(__dirname, './assets/javascript/teams/teams.jsx'),
        'edit-team': path.resolve(__dirname, './assets/javascript/teams/edit-team.jsx'),
        'avatar-upload': path.resolve(__dirname, './assets/javascript/users/avatar-upload.js'),
        'reports': path.resolve(__dirname, './assets/javascript/reports/ReportsDateRangePicker.jsx'),
        'bank-feed': path.resolve(__dirname, './assets/javascript/bank_feed/react/line-app.jsx'),
        'categorize-mode': path.resolve(__dirname, './assets/javascript/bank_feed/react/categorize-app.jsx'),
        'transactions': path.resolve(__dirname, './assets/javascript/transactions/transactions-app.jsx'),
        'budget-actual-app': path.resolve(__dirname, './assets/javascript/budget/budget-actual-app.jsx'),
        'budget-month-picker-app': path.resolve(__dirname, './assets/javascript/budget/budget-month-picker-app.jsx'),
        'budget-grid-app': path.resolve(__dirname, './assets/javascript/budget/budget-grid-app.jsx'),
        'budget-autosave': path.resolve(__dirname, './assets/javascript/budget/budget-autosave.js'),
        'budget-visibility': path.resolve(__dirname, './assets/javascript/budget/budget-visibility.js'),
        'budget-tabs': path.resolve(__dirname, './assets/javascript/budget/budget-tabs.js'),
        'goals-app': path.resolve(__dirname, './assets/javascript/budget/goals-app.js'),
        'goal-form': path.resolve(__dirname, './assets/javascript/budget/goal-form.js'),
        'date-field': path.resolve(__dirname, './assets/javascript/common/date-field-mount.jsx'),
        'accounts-board-app': path.resolve(__dirname, './assets/javascript/accounts/accounts-board-app.jsx'),
        'account-activity-editor': path.resolve(__dirname, './assets/javascript/accounts/account-activity-editor.jsx'),
        'account-charts': path.resolve(__dirname, './assets/javascript/accounts/account-charts.js'),
        'manage-modals': path.resolve(__dirname, './assets/javascript/accounts/manage-modals.jsx'),
        'onboarding-app': path.resolve(__dirname, './assets/javascript/onboarding/onboarding-app.jsx'),
        'task-rail-app': path.resolve(__dirname, './assets/javascript/onboarding/task-rail-app.jsx'),
        'onboarding-resume': path.resolve(__dirname, './assets/javascript/onboarding/resume.js'),
        'ynab-import-app': path.resolve(__dirname, './assets/javascript/ynab_import/ynab-import-app.jsx'),
        'data-transfer-app': path.resolve(__dirname, './assets/javascript/portability/data-transfer-app.jsx'),
        'reconcile-app': path.resolve(__dirname, './assets/javascript/reconcile/reconcile-app.jsx'),
        'rules-app': path.resolve(__dirname, './assets/javascript/rules/rules-app.jsx'),
        'recurring-list': path.resolve(__dirname, './assets/javascript/bank_feed/recurring-list.js'),
        'reconcile-statement': path.resolve(__dirname, './assets/javascript/reconcile/statement-page.js'),
        'monthly-review-app': path.resolve(__dirname, './assets/javascript/monthly_review/monthly-review-app.jsx'),
        'monthly-review-resume': path.resolve(__dirname, './assets/javascript/monthly_review/resume.js'),
        'net-worth-month-picker': path.resolve(__dirname, './assets/javascript/reports/NetWorthTrendMonthPicker.jsx'),
        'home-net-worth-chart': path.resolve(__dirname, './assets/javascript/dashboard/home-net-worth-chart.js'),
        // The report pages' charts, each loaded from the reports API (apps/reports/api.py).
        'spending-report': path.resolve(__dirname, './assets/javascript/reports/spending-report.js'),
        'net-worth-report': path.resolve(__dirname, './assets/javascript/reports/net-worth-report.js'),
        'budget-goals-report': path.resolve(__dirname, './assets/javascript/reports/budget-goals-report.js'),
        'audit-log': path.resolve(__dirname, './assets/javascript/audit/audit-log.js'),
        'unassigned-pill': path.resolve(__dirname, './assets/javascript/unassigned/unassigned-pill.js'),
      },
      output: {
        // Output JS bundles to js/ directory with -bundle suffix
        entryFileNames: `js/[name]-bundle.js`,
        // For shared chunks, keep hash for cache busting
        chunkFileNames: `js/[name]-[hash].js`,
        // For CSS and other assets
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith('.css')) {
            // Try to name CSS files like css/[entry_name].css, removing potential hash
            let baseName = path.basename(assetInfo.name, '.css');
            const hashPattern = /\.[0-9a-fA-F]{8}$/;
            baseName = baseName.replace(hashPattern, '');
            return `css/${baseName}.css`;
          }
          // Default for other assets (fonts, images, etc.)
          return `assets/[name]-[hash][extname]`;
        },
      },
    },
  },
  server: {
    port: 5173, // Default Vite dev server port, must match DJANGO_VITE settings
    strictPort: true, // Vite will exit if the port is already in use
    // Allow the Docker Compose service hostname so E2E tests (running inside the
    // web container) can fetch assets from the vite container.
    allowedHosts: ['vite'],
    hmr: {
      // host: 'localhost', // default of localhost is fine as long as Django is running there.
      // protocol: 'ws', // default of ws is fine. Change to 'wss' if Django (dev) server uses HTTPS.
    },
  },
});
