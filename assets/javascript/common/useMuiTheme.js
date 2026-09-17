import { useEffect, useMemo, useState } from 'react';

import { createTheme } from '@mui/material/styles';

/**
 * Shared MUI theme for the React islands embedded in Django templates.
 *
 * Every MUI subtree needs its own ThemeProvider — MUI defaults to its light
 * palette, so a component rendered without one stays light-on-light when the
 * app is in dark mode.
 *
 * `syncDarkMode` in templates/web/base.html is the single source of truth for
 * which theme is active: it resolves the stored preference (which may be an
 * explicit theme rather than "system") and toggles the `dark` class plus
 * `data-theme` to match. Reading prefers-color-scheme here as well would put
 * MUI in dark mode for someone who explicitly chose light on a dark-set OS, so
 * the class alone decides.
 *
 * We deliberately only set `palette.mode` rather than mapping the daisyUI
 * tokens across: those are oklch() values, and MUI's color utilities
 * (alpha/lighten/darken) can't parse them. MUI's own light/dark palettes sit
 * close enough to the koala surfaces, and the typography below keeps the two
 * systems visually consistent where it matters most.
 */
const useMuiTheme = () => {
  const [isDark, setIsDark] = useState(
    () => document.documentElement.classList.contains('dark')
  );

  // Re-read on theme flips, otherwise the subtree keeps its original palette
  // until a full page reload. Same approach as reports/chart-theme.js.
  useEffect(() => {
    const root = document.documentElement;
    const observer = new MutationObserver(() => {
      setIsDark(root.classList.contains('dark'));
    });
    observer.observe(root, { attributes: true, attributeFilter: ['class', 'data-theme'] });
    return () => observer.disconnect();
  }, []);

  return useMemo(
    () =>
      createTheme({
        palette: { mode: isDark ? 'dark' : 'light' },
        typography: {
          fontFamily: "'Inter Variable', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif",
        },
      }),
    [isDark]
  );
};

export default useMuiTheme;
