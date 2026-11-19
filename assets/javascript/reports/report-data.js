/* globals gettext */
import { DashboardApi, ReportsApi } from 'api-client';

import { apiCall, getApiConfiguration } from '../api';
import { readBook } from '../common/book';

/**
 * Loading report figures for the server-rendered report pages and the dashboard.
 *
 * The pages render their tables on the server; their charts load the same figures
 * from the reports API (`apps/reports/api.py`, `apps/web/api.py`) through the
 * generated client. The generated paths are absolute, so the page's origin is the base.
 */
export const getReportsApi = () => new ReportsApi(getApiConfiguration(window.location.origin));
export const getDashboardApi = () => new DashboardApi(getApiConfiguration(window.location.origin));

/** The page's book slugs (`book-base`), for `api.call({ ...bookParams(), ... })`. */
export const bookParams = () => readBook().params;

/** A `YYYY-MM-DD` string from the client's `Date` (parsed as UTC midnight, so UTC gives the same day back). */
export const isoDate = (value) => (value instanceof Date ? value.toISOString().slice(0, 10) : value);

/** A `YYYY-MM-DD` string as the `Date` the generated client sends back as that same day. */
export const apiDate = (value) => (value ? new Date(`${value}T00:00:00Z`) : undefined);

/** Decimal strings (money on the wire) as numbers for a chart. */
export const numbers = (values) => (values || []).map(Number);

/**
 * Show a spinner over `canvas` until `request` settles, then hand its result to
 * `draw` -- or replace the spinner with the server's reason when it fails.
 */
export async function loadChart(canvas, request, draw) {
  const frame = canvas.parentElement;
  frame.classList.add('relative');
  const overlay = document.createElement('div');
  overlay.className = 'absolute inset-0 flex items-center justify-center';
  overlay.dataset.chartLoading = '';
  overlay.innerHTML = '<span class="loading loading-spinner loading-md text-base-content/40"></span>';
  overlay.firstElementChild.setAttribute('aria-label', gettext('Loading'));
  frame.appendChild(overlay);
  try {
    const data = await apiCall(request());
    overlay.remove();
    draw(data);
  } catch (error) {
    overlay.className = 'absolute inset-0 flex items-center justify-center text-sm text-error text-center p-4';
    overlay.textContent = `${gettext('The chart could not be loaded.')} ${error.message || ''}`.trim();
  }
}

/** Run `load` once the page is parsed (entries load as modules, possibly after DOMContentLoaded). */
export function onReady(load) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
}
