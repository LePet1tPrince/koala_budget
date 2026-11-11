'use strict';
/**
 * Dollar Flow filters (templates/reports/components/dollar_flow.html).
 *
 * Each level is a dropdown of checkboxes, checked = shown. On any change the
 * unchecked values become repeated `hide` params; the page is fetched with them and
 * only #dollar-flow-body is swapped, so the open dropdown stays open. The URL is
 * updated in place and the month links carry the same filters.
 */

const BODY = 'dollar-flow-body';

function hiddenValues(form) {
  return [...form.querySelectorAll('input[type=checkbox]')].filter((box) => !box.checked).map((box) => box.value);
}

function withFilters(href, hidden) {
  const url = new URL(href, window.location.href);
  url.searchParams.delete('hide');
  hidden.forEach((value) => url.searchParams.append('hide', value));
  return url;
}

function updateCounts(form) {
  form.querySelectorAll('details[data-level]').forEach((level) => {
    const count = [...level.querySelectorAll('input[type=checkbox]')].filter((box) => !box.checked).length;
    const badge = level.querySelector('[data-hidden-count]');
    badge.textContent = String(count);
    badge.classList.toggle('hidden', count === 0);
  });
  const reset = form.querySelector('[data-reset-filters]');
  if (reset) reset.classList.toggle('hidden', hiddenValues(form).length === 0);
}

let pending = null;

async function apply(form) {
  const hidden = hiddenValues(form);
  const url = withFilters(window.location.href, hidden);
  url.searchParams.set('month', form.elements.month.value);
  updateCounts(form);
  document.querySelectorAll('[data-keep-flow-filters]').forEach((link) => {
    link.href = withFilters(link.getAttribute('href'), hidden).search || '?';
  });
  window.history.replaceState(null, '', url);

  // Only the latest request's answer is swapped in.
  const controller = new AbortController();
  if (pending) pending.abort();
  pending = controller;
  const body = document.getElementById(BODY);
  body.setAttribute('aria-busy', 'true');
  try {
    const response = await fetch(url, { signal: controller.signal, credentials: 'same-origin' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const page = new DOMParser().parseFromString(await response.text(), 'text/html');
    const next = page.getElementById(BODY);
    if (next) body.replaceWith(next);
  } catch (error) {
    if (error.name !== 'AbortError') window.location.assign(url);
  } finally {
    if (pending === controller) pending = null;
    document.getElementById(BODY)?.removeAttribute('aria-busy');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('[data-dollar-flow-filters]');
  if (!form) return;

  form.addEventListener('change', (event) => {
    if (event.target.matches('input[type=checkbox]')) apply(form);
  });
  form.addEventListener('click', (event) => {
    const toggle = event.target.closest('[data-set-all]');
    if (!toggle) return;
    const show = toggle.dataset.setAll === 'true';
    toggle
      .closest('details')
      .querySelectorAll('input[type=checkbox]')
      .forEach((box) => {
        box.checked = show;
      });
    apply(form);
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    apply(form);
  });
  // One dropdown open at a time; a click outside closes it.
  form.querySelectorAll('details').forEach((details) => {
    details.addEventListener('toggle', () => {
      if (!details.open) return;
      form.querySelectorAll('details[open]').forEach((other) => {
        if (other !== details) other.open = false;
      });
    });
  });
  document.addEventListener('click', (event) => {
    if (!form.contains(event.target)) form.querySelectorAll('details[open]').forEach((d) => (d.open = false));
  });
});
