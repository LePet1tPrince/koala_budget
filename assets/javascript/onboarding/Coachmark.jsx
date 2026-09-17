/* globals gettext */

import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';

/**
 * A tooltip anchored to a control elsewhere on the page.
 *
 * Purely additive and fail-safe: it polls briefly for the anchor and, if the
 * selector matches nothing, renders nothing at all. The rail's own copy already
 * tells the user what to do, so a missing coach mark costs a nicety rather than
 * the instruction — which matters, because the anchors point at controls in other
 * components that are free to change.
 *
 * Portaled to the body and fixed-positioned, the same technique the CSV wizard
 * uses for its category dropdown: an ancestor with a transform would otherwise
 * become the containing block and the mark would land in the wrong place.
 */
const POLL_MS = 250;
const GIVE_UP_AFTER = 12; // ~3s — long enough for a React island to mount

const Coachmark = ({ selector, text, onDismiss }) => {
  const [rect, setRect] = useState(null);

  useEffect(() => {
    if (!selector) return undefined;

    let tries = 0;
    let frame = null;

    const measure = () => {
      const target = document.querySelector(selector);
      if (target) {
        const box = target.getBoundingClientRect();
        // A zero-size box means it is in the DOM but not laid out yet.
        if (box.width || box.height) {
          setRect(box);
          return true;
        }
      }
      return false;
    };

    const tick = () => {
      if (measure()) return;
      if (++tries >= GIVE_UP_AFTER) return;
      frame = setTimeout(tick, POLL_MS);
    };
    tick();

    const reposition = () => measure();
    window.addEventListener('resize', reposition);
    window.addEventListener('scroll', reposition, true);

    return () => {
      clearTimeout(frame);
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
    };
  }, [selector]);

  if (!rect) return null;

  /*
    Beside the anchor when there is room, below it otherwise.

    Placing it below by default covered whatever sat under the anchor — on the
    bank feed that is the next account card, so the mark hid one of the very
    things it was pointing the user at.
  */
  const WIDTH = 272;
  const GAP = 12;
  const room = {
    right: window.innerWidth - rect.right - GAP,
    left: rect.left - GAP,
    below: window.innerHeight - rect.bottom - GAP,
  };

  let style;
  if (room.right >= WIDTH) {
    style = { top: rect.top, left: rect.right + GAP };
  } else if (room.left >= WIDTH) {
    style = { top: rect.top, left: rect.left - WIDTH - GAP };
  } else if (room.below >= 120) {
    style = { top: rect.bottom + GAP, left: Math.max(GAP, Math.min(rect.left, window.innerWidth - WIDTH - GAP)) };
  } else {
    style = {
      bottom: window.innerHeight - rect.top + GAP,
      left: Math.max(GAP, Math.min(rect.left, window.innerWidth - WIDTH - GAP)),
    };
  }

  // Never let it run off the bottom of the viewport when anchored by `top`.
  if (style.top !== undefined) {
    style.top = Math.max(GAP, Math.min(style.top, window.innerHeight - 140));
  }

  return createPortal(
    <>
      <span
        className="coachmark-ring"
        style={{ top: rect.top - 4, left: rect.left - 4, width: rect.width + 8, height: rect.height + 8 }}
        aria-hidden="true"
      />
      <div className="coachmark" style={style} role="note" data-testid="onboarding-coachmark">
        <p className="text-sm">{text}</p>
        <button type="button" className="coachmark-dismiss" onClick={onDismiss}>
          {gettext('Got it')}
        </button>
      </div>
    </>,
    document.body,
  );
};

export default Coachmark;
