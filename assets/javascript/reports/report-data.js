/**
 * Report figures for the server-rendered report pages and the dashboard.
 *
 * The pages render their tables on the server, and the same view embeds the body its
 * API endpoint (`apps/reports/api.py`, `apps/web/api.py`) would return for the page's
 * own parameters (a `json_script`), so the charts don't fetch it a second time.
 * `pageData` reads it through the generated client's `…FromJSON`, so a chart sees the
 * same object an `api-client` call would hand it.
 */

export { pageData } from '../api';

/** A `YYYY-MM-DD` string from the client's `Date` (parsed as UTC midnight, so UTC gives the same day back). */
export const isoDate = (value) => (value instanceof Date ? value.toISOString().slice(0, 10) : value);

/** Decimal strings (money on the wire) as numbers for a chart. */
export const numbers = (values) => (values || []).map(Number);

/** Run `load` once the page is parsed (entries load as modules, possibly after DOMContentLoaded). */
export function onReady(load) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
}
