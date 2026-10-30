/* globals gettext, interpolate */

import React from 'react';

import Icon from '../../common/Icon';
import { usePlaidLinkFlow } from './PlaidLinkButton';

/** What each connection status asks of the user (apps.plaid.models.PlaidItem.STATUS_*). */
const MESSAGES = {
  login_required: gettext('%s needs you to sign in again before it can sync.'),
  pending_expiration: gettext('Your access to %s expires soon. Reconnect to keep it syncing.'),
  pending_disconnect: gettext('%s will disconnect soon. Reconnect to keep it syncing.'),
  revoked: gettext('Access to %s was revoked at the bank. Reconnect to resume syncing.'),
  error: gettext('%s could not sync. Reconnecting may fix it.'),
};

const NEW_ACCOUNTS = gettext('%s has accounts you have not added yet.');

const ItemAlert = ({ item, book, allAccounts, plaidClient, onReconnected }) => {
  const { handleClick, loading, modal } = usePlaidLinkFlow({
    book,
    allAccounts,
    plaidClient,
    item,
    onSuccess: onReconnected,
  });
  const message =
    item.status !== 'healthy' ? MESSAGES[item.status] || MESSAGES.error : NEW_ACCOUNTS;
  const urgent = item.status === 'login_required' || item.status === 'revoked';

  return (
    <div
      className={`alert ${urgent ? 'alert-warning' : 'alert-info'} alert-soft`}
      role="status"
      data-testid={`plaid-item-alert-${item.id}`}
    >
      <Icon name="exclamation-triangle" className="inline-block shrink-0 w-4 h-4" />
      <span>
        {interpolate(message, [item.institutionName])}
        {item.errorMessage && <span className="block text-xs opacity-80">{item.errorMessage}</span>}
      </span>
      <button
        type="button"
        className="btn btn-sm"
        onClick={handleClick}
        disabled={loading}
        data-testid={`plaid-reconnect-${item.id}`}
      >
        {loading && <span className="loading loading-spinner loading-xs" />}
        {item.status === 'healthy' ? gettext('Add accounts') : gettext('Reconnect')}
      </button>
      {modal}
    </div>
  );
};

/**
 * One alert per bank connection that needs the user: sign in again, renew
 * consent, or share accounts Plaid found. Each opens Link's update mode.
 */
const PlaidItemAlerts = ({ items, book, allAccounts, plaidClient, onReconnected }) => {
  const needing = items.filter((item) => item.needsAttention);
  if (needing.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      {needing.map((item) => (
        <ItemAlert
          key={item.id}
          item={item}
          book={book}
          allAccounts={allAccounts}
          plaidClient={plaidClient}
          onReconnected={onReconnected}
        />
      ))}
    </div>
  );
};

export default PlaidItemAlerts;
