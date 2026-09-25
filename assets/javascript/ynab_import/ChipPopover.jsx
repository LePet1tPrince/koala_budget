import React, { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

import { portalTarget, useAnchoredPosition } from '../common/popoverPosition';

/**
 * The panel a chip opens: portaled and fixed-positioned under its trigger (see
 * `common/popoverPosition`), closed by Escape or a pointer landing outside it.
 *
 * Shared by the row chips (`ChipSelect`) and the name chips at the top of a
 * screen (`NameBank`), so both open, place and dismiss the same way.
 */
const ChipPopover = ({ open, triggerRef, onClose, testId, children }) => {
  const panelRef = useRef(null);
  const { style, measure } = useAnchoredPosition(open, triggerRef, panelRef, { minWidth: 224 });

  // The panel changes size as a list filters or a form opens inside it.
  useEffect(() => {
    if (!open || !panelRef.current || typeof ResizeObserver === 'undefined') return undefined;
    measure();
    const observer = new ResizeObserver(() => measure());
    observer.observe(panelRef.current);
    return () => observer.disconnect();
  }, [open, measure]);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => {
      if (triggerRef.current?.contains(e.target) || panelRef.current?.contains(e.target)) return;
      onClose();
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open, onClose, triggerRef]);

  if (!open) return null;

  return createPortal(
    <div
      ref={panelRef}
      className="fixed z-[1200] flex flex-col overflow-hidden rounded-xl border border-base-300 bg-base-100 p-1 shadow-lg"
      // Transparent rather than hidden while it measures itself on first paint: a
      // hidden element cannot take focus, and what opens in it focuses on mount.
      style={
        style
          ? { ...style, maxHeight: Math.min(style.maxHeight, 360) }
          : { top: 0, left: 0, opacity: 0, pointerEvents: 'none' }
      }
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          onClose();
          triggerRef.current?.focus();
        }
      }}
      data-testid={testId}
    >
      {children}
    </div>,
    portalTarget(triggerRef.current),
  );
};

export default ChipPopover;
