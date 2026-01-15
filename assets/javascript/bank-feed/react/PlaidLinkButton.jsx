/* globals gettext */

import React, { useCallback, useEffect, useState } from 'react';
import { apiRequest, handleApiError } from './utils';

import PlaidAccountMapper from './PlaidAccountMapper';
import { usePlaidLink } from 'react-plaid-link';

/**
 * PlaidLinkButton - Component to handle Plaid Link integration
 *
 * This component:
 * 1. Fetches a link_token from the backend
 * 2. Initializes Plaid Link with the token
 * 3. Handles the OAuth flow
 * 4. Exchanges the public_token for an access_token on the backend
 * 5. Triggers the account mapping flow
 */
const PlaidLinkButton = ({ teamSlug, allAccounts, onSuccess }) => {
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
      const response = await apiRequest(`/a/${teamSlug}/plaid/api/link-token/`, {
        method: 'POST',
      });

      await handleApiError(response, gettext('Failed to initialize Plaid Link. Please try again.'));
      const data = await response.json();
      setLinkToken(data.link_token);
    } catch (err) {
      console.error('Error fetching link token:', err);
      setError(err.message);
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
      const response = await apiRequest(`/a/${teamSlug}/plaid/api/exchange-token/`, {
        method: 'POST',
        body: JSON.stringify({
          public_token,
          institution_id: metadata.institution.institution_id,
          accounts: metadata.accounts,
        }),
      });

      await handleApiError(response, gettext('Failed to link account. Please try again.'));
      const data = await response.json();

      // Show account mapper with the newly created Plaid accounts
      setNewPlaidAccounts(data.accounts || []);
      setShowMapper(true);
    } catch (err) {
      console.error('Error exchanging token:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [teamSlug]);

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
   * Handle button click - fetch token to start the flow
   */
  const handleClick = () => {
    if (!linkToken) {
      fetchLinkToken();
    } else if (ready) {
      open();
    }
  };

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
};

export default PlaidLinkButton;

