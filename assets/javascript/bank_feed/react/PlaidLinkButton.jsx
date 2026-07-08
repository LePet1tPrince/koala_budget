/* globals gettext */

import React, { useCallback, useEffect, useState } from 'react';

import PlaidAccountMapper from './PlaidAccountMapper';
import { usePlaidLink } from 'react-plaid-link';

/**
 * usePlaidLinkFlow - headless Plaid Link integration
 *
 * Handles the full flow (fetch link_token, open Plaid Link, exchange the
 * public_token, show the account mapper) and hands back a `handleClick`
 * trigger plus a `modal` element to render (error alert + account mapper
 * dialog) so callers can supply their own trigger UI (button, menu item, …).
 */
export const usePlaidLinkFlow = ({ teamSlug, allAccounts, onSuccess, plaidClient }) => {
  const [linkToken, setLinkToken] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showMapper, setShowMapper] = useState(false);
  const [newPlaidAccounts, setNewPlaidAccounts] = useState([]);

  /**
   * Fetch link_token from backend
   */
  const fetchLinkToken = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await plaidClient.plaidCreateLinkToken({
        teamSlug: teamSlug,
      });
      setLinkToken(data.linkToken);
    } catch (err) {
      console.error('Error fetching link token:', err);
      setError(err.message || gettext('Failed to initialize Plaid Link. Please try again.'));
    } finally {
      setLoading(false);
    }
  };

  /**
   * Handle successful Plaid Link flow
   * Exchange public_token for access_token on backend
   */
  const onPlaidSuccess = useCallback(async (public_token, metadata) => {
    setLoading(true);
    try {
      const data = await plaidClient.plaidExchangePublicToken({
        teamSlug: teamSlug,
        exchangePublicTokenRequest: {
          publicToken: public_token,
          institutionId: metadata.institution?.institution_id ?? null,
          accounts: metadata.accounts,
        },
      });

      // Show account mapper with the newly created Plaid accounts
      setNewPlaidAccounts(data.accounts || []);
      setShowMapper(true);
    } catch (err) {
      console.error('Error exchanging token:', err);
      setError(err.message || gettext('Failed to link account. Please try again.'));
    } finally {
      setLoading(false);
    }
  }, [teamSlug, plaidClient]);

  /**
   * Handle Plaid Link exit (user closed without completing)
   */
  const onPlaidExit = useCallback((err, metadata) => {
    if (err) {
      console.error('Plaid Link error:', err, metadata);
      setError(gettext('An error occurred. Please try again.'));
    }
    setLoading(false);
    setLinkToken(null); // Reset token so user can try again
  }, []);

  /**
   * Handle Plaid Link events (for debugging/analytics)
   */
  const onPlaidEvent = useCallback((eventName, metadata) => {
    console.log('Plaid Link event:', eventName, metadata);
  }, []);

  // Configure Plaid Link
  const config = {
    token: linkToken,
    onSuccess: onPlaidSuccess,
    onExit: onPlaidExit,
    onEvent: onPlaidEvent,
  };

  const { open, ready } = usePlaidLink(config);

  // Auto-open Plaid Link when ready
  useEffect(() => {
    if (linkToken && ready && !showMapper) {
      setLoading(false);
      open();
    }
  }, [linkToken, ready, open, showMapper]);

  /**
   * Handle trigger click - fetch token to start the flow
   */
  const handleClick = () => {
    if (!linkToken) {
      fetchLinkToken();
    } else if (ready) {
      open();
    }
  };

  const modal = (
    <>
      {error && (
        <div className="alert alert-error mt-4">
          <i className="fa fa-exclamation-circle"></i>
          <span>{error}</span>
        </div>
      )}

      {/* Account Mapper Modal */}
      {showMapper && (
        <PlaidAccountMapper
          teamSlug={teamSlug}
          plaidAccounts={newPlaidAccounts}
          ledgerAccounts={allAccounts}
          plaidClient={plaidClient}
          onComplete={() => {
            setShowMapper(false);
            setLinkToken(null);
            if (onSuccess) {
              onSuccess();
            }
          }}
          onCancel={() => {
            setShowMapper(false);
            setLinkToken(null);
          }}
        />
      )}
    </>
  );

  return { handleClick, loading, modal };
};

/**
 * PlaidLinkButton - default button trigger built on usePlaidLinkFlow
 */
const PlaidLinkButton = ({ teamSlug, allAccounts, onSuccess, plaidClient }) => {
  const { handleClick, loading, modal } = usePlaidLinkFlow({ teamSlug, allAccounts, onSuccess, plaidClient });

  return (
    <>
      <button
        onClick={handleClick}
        disabled={loading}
        className="btn btn-primary"
      >
        {loading ? (
          <>
            <span className="loading loading-spinner loading-sm"></span>
            {gettext('Loading...')}
          </>
        ) : (
          <>
            <i className="fa fa-plus mr-2"></i>
            {gettext('Link Bank Account')}
          </>
        )}
      </button>

      {modal}
    </>
  );
};

export default PlaidLinkButton;
