import { useCallback, useRef, useState } from 'react';

// How far (px) a card must travel to count as a swipe rather than a nudge.
const COMMIT_X = 90;
const COMMIT_Y = 80;

/**
 * Drag-to-decide on the top card, for touch and pen (a mouse drags text, not
 * cards). Right calls `onRight`, left `onLeft`, up `onUp`; a short drag springs
 * back. Returns the pointer handlers for the card, its current `offset` to draw
 * and the direction it is leaning (`'right'|'left'|'up'|null`) for the hint.
 *
 * A drag that starts in a field, button or link is left to that element.
 */
export function useSwipe({ onLeft, onRight, onUp, disabled = false }) {
  const start = useRef(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });

  const lean = (x, y) => {
    if (Math.abs(x) < 24 && Math.abs(y) < 24) return null;
    if (-y > Math.abs(x)) return 'up';
    return x > 0 ? 'right' : 'left';
  };

  const onPointerDown = useCallback(
    (e) => {
      if (disabled || e.pointerType === 'mouse') return;
      if (e.target.closest('input, textarea, select, button, a, label')) return;
      start.current = { x: e.clientX, y: e.clientY, id: e.pointerId };
      e.currentTarget.setPointerCapture?.(e.pointerId);
    },
    [disabled],
  );

  const onPointerMove = useCallback((e) => {
    if (!start.current || start.current.id !== e.pointerId) return;
    setOffset({ x: e.clientX - start.current.x, y: Math.min(0, e.clientY - start.current.y) });
  }, []);

  const finish = useCallback(
    (e) => {
      if (!start.current || start.current.id !== e.pointerId) return;
      const x = e.clientX - start.current.x;
      const y = e.clientY - start.current.y;
      start.current = null;
      setOffset({ x: 0, y: 0 });
      const vibrate = () => navigator.vibrate?.(12);
      if (-y > COMMIT_Y && -y > Math.abs(x)) {
        vibrate();
        onUp?.();
      } else if (x > COMMIT_X) {
        vibrate();
        onRight?.();
      } else if (x < -COMMIT_X) {
        vibrate();
        onLeft?.();
      }
    },
    [onLeft, onRight, onUp],
  );

  const cancel = useCallback(() => {
    start.current = null;
    setOffset({ x: 0, y: 0 });
  }, []);

  return {
    handlers: { onPointerDown, onPointerMove, onPointerUp: finish, onPointerCancel: cancel },
    offset,
    leaning: lean(offset.x, offset.y),
  };
}
