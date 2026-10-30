/* globals gettext, interpolate, ngettext */

import React, { useState } from 'react';

import Icon from '../../common/Icon';
import PlaidAccountMapper from './PlaidAccountMapper';
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
 * A linked bank with accounts that are neither mapped nor ignored: their
 * transactions aren't imported until the user picks a ledger account (which
 * backfills their history) or says not to import them.
 */
const UnmappedAlert = ({ item, plaidAccounts, book, allAccounts, plaidClient, onMapped }) => {
  const [open, setOpen] = useState(false);
  const unmapped = plaidAccounts.filter((pa) => pa.item === item.id && pa.account == null && !pa.isIgnored);
  if (unmapped.length === 0) return null;
  return (
    <div className="alert alert-info alert-soft" role="status" data-testid={`plaid-unmapped-alert-${item.id}`}>
      <Icon name="exclamation-triangle" className="inline-block shrink-0 w-4 h-4" />
      <span>
        {interpolate(
          ngettext(
            '%s has %s account whose transactions are not imported yet.',
            '%s has %s accounts whose transactions are not imported yet.',
            unmapped.length,
          ),
          [item.institutionName, unmapped.length],
        )}
      </span>
      <button type="button" className="btn btn-sm" onClick={() => setOpen(true)} data-testid={`plaid-map-${item.id}`}>
        {gettext('Choose accounts')}
      </button>
      {open && (
        <PlaidAccountMapper
          book={book}
          plaidAccounts={unmapped}
          ledgerAccounts={allAccounts}
          plaidClient={plaidClient}
          onComplete={() => {
            setOpen(false);
            if (onMapped) onMapped();
          }}
          onCancel={() => setOpen(false)}
        />
      )}
    </div>
  );
};

/**
 * One alert per bank connection that needs the user: sign in again, renew
 * consent, or share accounts Plaid found (each opens Link's update mode) --
 * or map accounts whose transactions aren't imported yet.
 */
const PlaidItemAlerts = ({ items, plaidAccounts = [], book, allAccounts, plaidClient, onReconnected }) => {
  const shown = items.filter((item) => item.needsAttention || item.unmappedAccounts > 0);
  if (shown.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      {shown.map((item) => (
        <React.Fragment key={item.id}>
          {item.needsAttention && (
            <ItemAlert
              item={item}
              book={book}
              allAccounts={allAccounts}
              plaidClient={plaidClient}
              onReconnected={onReconnected}
            />
          )}
          <UnmappedAlert
            item={item}
            plaidAccounts={plaidAccounts}
            book={book}
            allAccounts={allAccounts}
            plaidClient={plaidClient}
            onMapped={onReconnected}
          />
        </React.Fragment>
      ))}
    </div>
  );
};

export default PlaidItemAlerts;
