/* globals gettext, interpolate */

import React, { useState } from 'react';

import Modal from '../../common/Modal';

/**
 * Disconnect a linked bank (POST plaid items/{id}/remove/). It stops syncing;
 * the transactions it already imported stay, categorized or not.
 */
const DisconnectBankButton = ({ item, book, plaidClient, onDisconnected }) => {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const disconnect = async () => {
    setBusy(true);
    setError(null);
    try {
      await plaidClient.plaidItemsRemove({ ...book.params, id: item.id });
      setOpen(false);
      if (onDisconnected) onDisconnected();
    } catch (err) {
      console.error('Failed to disconnect bank:', err);
      setError(gettext('Could not disconnect this bank. Please try again.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        className="btn btn-ghost btn-xs"
        onClick={() => setOpen(true)}
        data-testid={`plaid-disconnect-${item.id}`}
      >
        {gettext('Disconnect')}
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        size="sm"
        testId="plaid-disconnect-dialog"
        initialFocus="[data-cancel]"
        title={interpolate(gettext('Disconnect %s?'), [item.institutionName])}
        actions={
          <>
            <button type="button" className="btn btn-ghost" data-cancel onClick={() => setOpen(false)}>
              {gettext('Keep it')}
            </button>
            <button
              type="button"
              className="btn btn-error"
              onClick={disconnect}
              disabled={busy}
              data-testid="plaid-disconnect-confirm"
            >
              {busy && <span className="loading loading-spinner loading-xs" />}
              {gettext('Disconnect')}
            </button>
          </>
        }
      >
        <p>
          {gettext(
            'New transactions will stop arriving from this bank. The transactions already imported stay where they are.',
          )}
        </p>
        {error && <p className="text-error mt-2">{error}</p>}
      </Modal>
    </>
  );
};

export default DisconnectBankButton;
