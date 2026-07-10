'use strict';
/**
 * Shared theming for the report charts: a fixed-order categorical palette
 * (validated for CVD separation and surface contrast on both the light and
 * dark app surfaces), theme-resolved ink/surface colors, and a helper that
 * re-resolves colors when the user flips light/dark mode without a reload.
 *
 * Categorical hues are assigned in this fixed order — never cycled. Charts
 * with more than CATEGORICAL_LIMIT series must fold the tail into "Other".
 */

const LIGHT_SERIES = ['#2a78d6', '#1baf7a', '#eda100', '#008300', '#4a3aa7', '#e34948', '#e87ba4', '#eb6834'];
const DARK_SERIES = ['#3987e5', '#199e70', '#c98500', '#008300', '#9085e9', '#e66767', '#d55181', '#d95926'];

export const CATEGORICAL_LIMIT = LIGHT_SERIES.length;

// Semantic money colors shared with the net worth chart (validated light+dark):
// inflows/assets green, outflows/liabilities red, net/emphasis blue.
export const MONEY = {
  in: 'rgb(22, 163, 74)',
  out: 'rgb(239, 68, 68)',
  net: 'rgb(59, 130, 246)',
  netFill: 'rgba(59, 130, 246, 0.10)',
};

export const isDarkTheme = () =>
  (document.documentElement.getAttribute('data-theme') || '').includes('dark');

export const seriesColors = (count) =>
  (isDarkTheme() ? DARK_SERIES : LIGHT_SERIES).slice(0, Math.min(count, CATEGORICAL_LIMIT));

export const getInk = (el) => getComputedStyle(el).color;

export const getSurface = (el) =>
  getComputedStyle(el.closest('.card') || document.body).backgroundColor;

export const GRID = 'rgba(128, 128, 128, 0.15)';

export const currency = (value) =>
  `$${Number(value).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;

export const compactCurrency = (value) => `$${Number(value).toLocaleString()}`;

/**
 * Re-run `apply(chart)` whenever the data-theme attribute changes, so charts
 * recolor on in-page theme flips. `apply` receives the chart and should set
 * colors from the current theme, then the chart is updated without animation.
 */
export const observeTheme = (chart, apply) => {
  const observer = new MutationObserver(() => {
    apply(chart);
    chart.update('none');
  });
  observer.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
};

/** Month-start ISO date ('YYYY-MM-DD' or 'YYYY-MM') → short display label, timezone-safe. */
export const monthLabel = (iso) => {
  const [year, month] = iso.split('-').map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString(undefined, {month: 'short', year: 'numeric'});
};
