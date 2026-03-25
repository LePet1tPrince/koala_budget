/* globals gettext */

import React from 'react';
import { formatCurrency } from '../../utilities/currency';

/**
 * AccountCard component - displays an account with bank feed
 * Shows account name, number, and selection state
 */
const AccountCard = ({ account, isSelected, onClick }) => {
  const cardClasses = `card bg-base-200 shadow-md cursor-pointer transition-all hover:shadow-lg ${
    isSelected ? 'ring-2 ring-primary' : ''
  }`;

  return (
    <div className={cardClasses} onClick={() => onClick(account)} data-testid={`account-card-${account.id}`}>
      <div className="card-body p-4">
        <h3 className="card-title text-base">
          {account.name}
          {isSelected && (
            <span className="badge badge-primary badge-sm ml-2">
              {gettext('Selected')}
            </span>
          )}
        </h3>
        <p className="text-xs text-base-content/60">
          {account.account_group_name}
        </p>
        <div className="text-xs text-base-content/60 mt-2 space-y-1">
          <p>
            {gettext('Categorized Balance:')} {formatCurrency(account.balance)}
          </p>
          <p>
            {gettext('Reconciled Balance:')} {formatCurrency(account.reconciled_balance || 0)}
          </p>
        </div>
      </div>
    </div>
  );
};

export default AccountCard;
