/* globals gettext */
import React from 'react';

/**
 * AccountCard component - displays an account with bank feed
 * Shows account name, number, and selection state
 */
const AccountCard = ({ account, isSelected, onClick }) => {
  const cardClasses = `card bg-base-200 shadow-md cursor-pointer transition-all hover:shadow-lg ${
    isSelected ? 'ring-2 ring-primary' : ''
  }`;

  return (
    <div className={cardClasses} onClick={() => onClick(account)}>
      <div className="card-body p-4">
        <h3 className="card-title text-base">
          {account.name}
          {isSelected && (
            <span className="badge badge-primary badge-sm ml-2">
              {gettext('Selected')}
            </span>
          )}
        </h3>
        <p className="text-sm text-base-content/70">
          {gettext('Account #')}{account.account_number}
        </p>
        <p className="text-xs text-base-content/60">
          {account.account_group_name}
        </p>
      </div>
    </div>
  );
};

export default AccountCard;

