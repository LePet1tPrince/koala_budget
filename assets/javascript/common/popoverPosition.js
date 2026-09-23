import { useCallback, useEffect, useLayoutEffect, useState } from 'react';

/* One positioning strategy for every popover in the app (restyle plan Phase 7).
 *
 * Panels are portaled and fixed-positioned rather than absolutely placed inside
 * their trigger. Two things forced this:
 *
 *  - daisyUI's `.modal-box` scrolls its overflow, so an absolutely-placed panel
 *    is clipped by the modal it sits in.
 *  - a `<dialog>` paints in the browser's top layer, so a panel portaled to
 *    `document.body` would vanish *behind* the modal it belongs to. The portal
 *    target is therefore the nearest ancestor `<dialog>`, falling back to body.
 */

const GUTTER = 8;

/** Where a panel of this size should sit, given its trigger. */
export const placePanel = (anchorRect, panelRect, { matchWidth = false, minWidth = 0 } = {}) => {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  // `minWidth` keeps a list opened from a narrow trigger (a table cell) readable.
  const width = matchWidth ? Math.max(anchorRect.width, minWidth) : panelRect.width;

  let left = anchorRect.left;
  if (left + width > vw - GUTTER) left = vw - GUTTER - width;
  if (left < GUTTER) left = GUTTER;

  // Below the trigger when it fits, above when it does not, and whichever side
  // has more room when neither does.
  const below = vh - anchorRect.bottom - GUTTER;
  const above = anchorRect.top - GUTTER;
  const height = panelRect.height;
  let top;
  let maxHeight;
  if (height <= below || below >= above) {
    top = anchorRect.bottom + 4;
    maxHeight = below;
  } else {
    top = Math.max(GUTTER, anchorRect.top - height - 4);
    maxHeight = above;
  }

  return { top, left, maxHeight, width: matchWidth ? width : undefined };
};

/** The element a panel must portal into to paint above its own context. */
export const portalTarget = (node) => node?.closest('dialog') ?? document.body;

/**
 * Track a trigger's position, re-measuring while the panel is open.
 *
 * `open` gates the listeners; `deps` re-measures when the panel's own size
 * changes (a filtered list gets shorter as the user types).
 */
export const useAnchoredPosition = (open, anchorRef, panelRef, options = {}) => {
  const [style, setStyle] = useState(null);
  const { matchWidth = false, minWidth = 0 } = options;

  const measure = useCallback(() => {
    const anchor = anchorRef.current;
    if (!anchor) return;
    const panel = panelRef.current;
    const panelRect = panel ? panel.getBoundingClientRect() : { width: 0, height: 0 };
    setStyle(placePanel(anchor.getBoundingClientRect(), panelRect, { matchWidth, minWidth }));
  }, [anchorRef, panelRef, matchWidth, minWidth]);

  useLayoutEffect(() => {
    if (!open) {
      setStyle(null);
      return;
    }
    measure();
  }, [open, measure]);

  useEffect(() => {
    if (!open) return undefined;
    // `true` for scroll: a scroll inside any ancestor moves the trigger too.
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [open, measure]);

  return { style, measure };
};
