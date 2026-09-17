import React, { useEffect, useRef } from 'react';

/* globals gettext */

/**
 * A daisyUI modal, replacing MUI's `Dialog` + `DialogTitle`/`DialogContent`/`DialogActions`
 * (restyle plan Phase 7).
 *
 * Rendered as a real `<dialog>` so the browser supplies the top layer, focus
 * trapping and the backdrop — MUI hand-rolled all three in a portal. `showModal()`
 * has to be called imperatively; React cannot express the open state as a prop.
 */
const SIZES = {
  sm: 'max-w-md',
  md: 'max-w-xl',
  lg: 'max-w-3xl',
};

const Modal = ({ open, onClose, title, children, actions, size = 'md', testId, bodyClassName = '' }) => {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  // Escape and backdrop clicks fire the dialog's own `cancel`/`close`, which must
  // be routed back to the owner or the component's state and the DOM diverge.
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const onCancel = (e) => {
      e.preventDefault();
      onClose?.();
    };
    el.addEventListener('cancel', onCancel);
    return () => el.removeEventListener('cancel', onCancel);
  }, [onClose]);

  return (
    <dialog ref={ref} className="modal" data-testid={testId}>
      <div className={`modal-box ${SIZES[size]} bg-base-100 border border-base-300`}>
        {title && <h3 className="mb-4 text-lg font-semibold">{title}</h3>}
        <div className={bodyClassName}>{children}</div>
        {actions && <div className="modal-action">{actions}</div>}
      </div>
      {/* daisyUI's click-outside-to-close: a full-bleed form whose submit closes. */}
      <form method="dialog" className="modal-backdrop">
        <button type="submit" aria-label={gettext('Close')} onClick={() => onClose?.()}>
          {gettext('Close')}
        </button>
      </form>
    </dialog>
  );
};

export default Modal;
