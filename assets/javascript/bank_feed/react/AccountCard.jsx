/* globals gettext */

import React from 'react';
import { formatCurrency } from '../../utilities/currency';
import { formatDate } from '../utils';

/**
 * AccountCard component - a compact, scannable row for the account picker.
 * Shows account name, institution, balance, and a badge when transactions need review.
 */
const AccountCard = ({ account, isSelected, onClick }) => {
  const isLiability = account.account_type === 'liability';
  const uncategorizedCount = account.uncategorized_count || 0;

  const rowClasses = `flex items-center gap-3 rounded-lg border px-3 py-2.5 cursor-pointer transition-colors ${
    isSelected
      ? 'border-primary bg-primary/10'
      : 'border-base-300 bg-base-100 hover:border-primary/40 hover:bg-base-200'
  }`;

  return (
    <div
      className={rowClasses}
      onClick={() => onClick(account)}
      role="button"
      tabIndex={0}
      aria-pressed={isSelected}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick(account);
        }
      }}
      data-testid={`account-card-${account.id}`}
    >
      <span className="relative shrink-0">
        <span
          className={`flex items-center justify-center w-8 h-8 rounded-full text-xs ${
            isLiability ? 'bg-warning/15 text-warning' : 'bg-primary/15 text-primary'
          }`}
          aria-hidden="true"
        >
          <i className={`fa ${isLiability ? 'fa-credit-card' : 'fa-university'}`}></i>
        </span>
        {uncategorizedCount > 0 && (
          <span
            className="absolute -top-1.5 -right-1.5 flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-error text-error-content text-[10px] font-semibold leading-none"
            title={`${uncategorizedCount} ${gettext('transactions awaiting categorization')}`}
          >
            {uncategorizedCount > 99 ? '99+' : uncategorizedCount}
          </span>
        )}
      </span>

      <div className="min-w-0 flex-1">
        <p className="font-medium text-sm truncate">{account.name}</p>
        <p className="text-xs text-base-content/60 truncate">
          {account.institution_name || account.account_group_name}
        </p>
      </div>

      <div className="flex flex-col items-end shrink-0 w-24">
        {account.latest_transaction_date && (
          <p className="text-[10px] text-base-content/50 tabular-nums truncate">
            {formatDate(account.latest_transaction_date)}
          </p>
        )}
        <p className="text-sm font-semibold tabular-nums text-right">
          {formatCurrency(account.categorized_balance ?? account.balance)}
        </p>
      </div>
    </div>
  );
};

export default AccountCard;
