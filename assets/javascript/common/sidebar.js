/**
 * Desktop sidebar: drag its right edge to resize, or collapse it to icons only.
 *
 * State lives on <html> -- `--sidebar-w` for the width, `data-sidebar="collapsed"`
 * for the collapsed state -- and is remembered per browser in localStorage. The
 * inline script in app_base.html applies the stored state before first paint;
 * this module only handles changes. CSS in app-components.css does the rest.
 *
 * Dragging narrower than COLLAPSE_BELOW collapses the sidebar; dragging a
 * collapsed one wider than that expands it again. Double-click the handle to
 * reset the width; with the handle focused, ←/→ resize and Enter toggles.
 */

const WIDTH_KEY = 'koala.sidebar.width';
const COLLAPSED_KEY = 'koala.sidebar.collapsed';
export const DEFAULT_WIDTH = 248;
export const MIN_WIDTH = 200;
export const MAX_WIDTH = 420;
const COLLAPSE_BELOW = 140;
const KEY_STEP = 16;

const root = document.documentElement;

function store(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Private windows and blocked storage: the sidebar still works, it just forgets.
  }
}

export function clampWidth(width) {
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(width)));
}

function currentWidth() {
  const value = parseInt(getComputedStyle(root).getPropertyValue('--sidebar-w'), 10);
  return Number.isFinite(value) ? value : DEFAULT_WIDTH;
}

function isCollapsed() {
  return root.dataset.sidebar === 'collapsed';
}

function setWidth(width, persist = true) {
  const clamped = clampWidth(width);
  root.style.setProperty('--sidebar-w', `${clamped}px`);
  if (persist) store(WIDTH_KEY, String(clamped));
  return clamped;
}

/**
 * Labels are screen-reader-only while collapsed, so a hover tooltip is the only
 * way a sighted user learns what an icon is. `title` is added only while
 * collapsed -- expanded, it would just repeat the visible label.
 */
function syncTitles(sidebar, collapsed) {
  sidebar.querySelectorAll('.side-link, .side-tile').forEach((el) => {
    const label = el.querySelector('.side-label, .side-tile-text');
    if (!label) return;
    if (collapsed) el.setAttribute('title', label.textContent.trim().replace(/\s+/g, ' '));
    else el.removeAttribute('title');
  });
}

function setCollapsed(sidebar, collapsed) {
  if (collapsed) root.dataset.sidebar = 'collapsed';
  else delete root.dataset.sidebar;
  store(COLLAPSED_KEY, collapsed ? '1' : '0');
  syncTitles(sidebar, collapsed);
  sidebar.querySelectorAll('[data-sidebar-toggle]').forEach((btn) => {
    const label = collapsed ? btn.dataset.labelExpand : btn.dataset.labelCollapse;
    btn.setAttribute('aria-expanded', String(!collapsed));
    btn.setAttribute('aria-label', label);
    btn.setAttribute('title', label);
  });
  const handle = sidebar.querySelector('[data-sidebar-resizer]');
  if (handle) handle.setAttribute('aria-valuenow', String(collapsed ? 0 : currentWidth()));
}

function bindResizer(sidebar, handle) {
  let startX = 0;
  let startWidth = 0;
  // The expanded width to come back to if this drag ends collapsed: the drag
  // shrinks the sidebar to MIN_WIDTH on its way below COLLAPSE_BELOW.
  let restoreWidth = DEFAULT_WIDTH;

  handle.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    startX = event.clientX;
    startWidth = sidebar.getBoundingClientRect().width;
    restoreWidth = currentWidth();
    root.setAttribute('data-sidebar-resizing', '');
  });

  handle.addEventListener('pointermove', (event) => {
    if (!handle.hasPointerCapture(event.pointerId)) return;
    const width = startWidth + (event.clientX - startX);
    if (width < COLLAPSE_BELOW) {
      if (!isCollapsed()) {
        setWidth(restoreWidth, false);
        setCollapsed(sidebar, true);
      }
      return;
    }
    if (isCollapsed()) setCollapsed(sidebar, false);
    setWidth(width, false);
  });

  const finish = (event) => {
    if (!handle.hasPointerCapture(event.pointerId)) return;
    handle.releasePointerCapture(event.pointerId);
    root.removeAttribute('data-sidebar-resizing');
    if (!isCollapsed()) setWidth(currentWidth());
    handle.setAttribute('aria-valuenow', String(isCollapsed() ? 0 : currentWidth()));
  };
  handle.addEventListener('pointerup', finish);
  handle.addEventListener('pointercancel', finish);

  handle.addEventListener('dblclick', () => {
    setCollapsed(sidebar, false);
    handle.setAttribute('aria-valuenow', String(setWidth(DEFAULT_WIDTH)));
  });

  handle.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      setCollapsed(sidebar, !isCollapsed());
      return;
    }
    const step = event.key === 'ArrowRight' ? KEY_STEP : event.key === 'ArrowLeft' ? -KEY_STEP : 0;
    if (!step) return;
    event.preventDefault();
    if (isCollapsed()) {
      if (step > 0) setCollapsed(sidebar, false);
      return;
    }
    handle.setAttribute('aria-valuenow', String(setWidth(currentWidth() + step)));
  });
}

function init() {
  const sidebar = document.querySelector('[data-sidebar-root]');
  if (!sidebar) return;
  // Reflect the state the inline script applied (titles, button label, aria).
  setCollapsed(sidebar, isCollapsed());
  sidebar.querySelectorAll('[data-sidebar-toggle]').forEach((btn) => {
    btn.addEventListener('click', () => setCollapsed(sidebar, !isCollapsed()));
  });
  const handle = sidebar.querySelector('[data-sidebar-resizer]');
  if (handle) bindResizer(sidebar, handle);
}

init();
