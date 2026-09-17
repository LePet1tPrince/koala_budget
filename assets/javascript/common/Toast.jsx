import React, { useEffect } from 'react';

/* globals gettext */

/** Transient message strip, replacing MUI's Snackbar + Alert. */
export const Toast = ({
  open,
  message,
  severity = 'info',
  onClose,
  autoHideMs = 4000,
  testId = 'toast',
  action = null,
}) => {
  useEffect(() => {
    if (!open) return undefined;
    const t = setTimeout(onClose, autoHideMs);
    return () => clearTimeout(t);
  }, [open, onClose, autoHideMs]);

  if (!open) return null;
  const cls = { success: 'alert-success', error: 'alert-error', warning: 'alert-warning', info: 'alert-info' }[severity];
  return (
    <div className="toast toast-end z-50" data-testid={testId}>
      <div className={`alert ${cls}`}>
        <span>{message}</span>
        {action}
        <button type="button" className="btn btn-ghost btn-xs" onClick={onClose} aria-label={gettext('Dismiss')}>
          ✕
        </button>
      </div>
    </div>
  );
};

export default Toast;
