import React, { useEffect, useRef } from 'react';

import Modal from '../../common/Modal';
import HealthCheck from './HealthCheck';

/**
 * Opens the review: is this month's data complete enough to trust the numbers?
 * Informational only -- closing it (button, Escape, backdrop) always continues.
 */
const HealthModal = ({ open, onClose, review, inboxUrl }) => {
  const continueRef = useRef(null);

  // showModal() focuses the first focusable element -- a flagged row, which would
  // pop its tooltip before anything is read. Modal's own effect runs first (child
  // before parent), so the dialog is already open here.
  useEffect(() => {
    if (open) continueRef.current?.focus();
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      testId="health-modal"
      title={`Is ${review.month_label}'s data complete?`}
      actions={
        <>
          {inboxUrl && !review.health.all_clear && (
            <a href={inboxUrl} className="btn btn-ghost" data-testid="health-modal-inbox">
              Go to the Inbox
            </a>
          )}
          <button
            ref={continueRef}
            type="button"
            className="btn btn-primary"
            onClick={onClose}
            data-testid="health-modal-continue"
          >
            Continue to review
          </button>
        </>
      }
    >
      <p className="text-base-content/70 mb-4">
        Before looking at numbers, let&apos;s make sure this month&apos;s data is trustworthy.
      </p>
      <HealthCheck review={review} />
    </Modal>
  );
};

export default HealthModal;
