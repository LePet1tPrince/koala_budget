/* globals gettext */

import React, { useState, useRef, useEffect, useMemo } from 'react';

const ACCOUNT_TYPE_LABELS = {
  asset: gettext('Assets'),
  liability: gettext('Liabilities'),
  income: gettext('Income'),
  expense: gettext('Expenses'),
  goal: gettext('Goals'),
};

const TYPE_ORDER = ['asset', 'liability', 'income', 'expense', 'goal'];

/**
 * AccountComboBox - Searchable dropdown for selecting an account.
 * Displays accounts grouped by type, with an inline search field.
 * Includes a "Create new account" option at the bottom.
 */
const AccountComboBox = ({ allAccounts, value, onChange, onCreateNew }) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const containerRef = useRef(null);
  const inputRef = useRef(null);

  const selectedAccount = useMemo(
    () => allAccounts.find((a) => a.id === value) || null,
    [allAccounts, value]
  );

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
        setSearch('');
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Focus search input when dropdown opens
  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus();
    }
  }, [open]);

  const groupedAccounts = useMemo(() => {
    const term = search.toLowerCase();
    const filtered = term
      ? allAccounts.filter((a) => a.name.toLowerCase().includes(term))
      : allAccounts;

    const groups = {};
    filtered.forEach((account) => {
      const type = account.account_type || 'other';
      if (!groups[type]) groups[type] = [];
      groups[type].push(account);
    });
    return groups;
  }, [allAccounts, search]);

  const orderedTypes = useMemo(() => {
    const types = Object.keys(groupedAccounts);
    return [
      ...TYPE_ORDER.filter((t) => types.includes(t)),
      ...types.filter((t) => !TYPE_ORDER.includes(t)),
    ];
  }, [groupedAccounts]);

  const hasResults = orderedTypes.length > 0;

  const handleSelect = (accountId) => {
    onChange(accountId);
    setOpen(false);
    setSearch('');
  };

  const handleClear = (e) => {
    e.stopPropagation();
    onChange(null);
    setOpen(false);
    setSearch('');
  };

  const handleCreateNew = () => {
    setOpen(false);
    setSearch('');
    onCreateNew();
  };

  return (
    <div ref={containerRef} className="relative w-full">
      {/* Trigger button */}
      <button
        type="button"
        className="btn btn-sm btn-outline w-full justify-between font-normal text-left"
        onClick={() => setOpen((o) => !o)}
      >
        <span className={selectedAccount ? '' : 'text-base-content/50'}>
          {selectedAccount ? selectedAccount.name : gettext('-- Leave uncategorized --')}
        </span>
        <div className="flex items-center gap-1">
          {selectedAccount && (
            <span
              className="text-base-content/40 hover:text-base-content cursor-pointer px-1"
              onMouseDown={handleClear}
              title={gettext('Clear selection')}
            >
              ✕
            </span>
          )}
          <i className={`fa fa-chevron-${open ? 'up' : 'down'} text-xs text-base-content/50`}></i>
        </div>
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute z-50 w-full mt-1 bg-base-100 border border-base-300 rounded-lg shadow-lg"
          style={{ minWidth: '100%', maxWidth: '400px' }}>
          {/* Search input */}
          <div className="p-2 border-b border-base-300">
            <input
              ref={inputRef}
              type="text"
              className="input input-bordered input-sm w-full"
              placeholder={gettext('Search accounts...')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
            />
          </div>

          {/* Options list */}
          <div className="max-h-60 overflow-y-auto">
            {/* Leave uncategorized option */}
            <div
              className={`px-3 py-2 cursor-pointer hover:bg-base-200 text-sm text-base-content/60 italic ${!value ? 'bg-primary/10 font-medium' : ''}`}
              onMouseDown={() => handleSelect(null)}
            >
              {gettext('-- Leave uncategorized --')}
            </div>

            {!hasResults && (
              <div className="px-3 py-3 text-sm text-base-content/50 text-center">
                {gettext('No accounts found')}
              </div>
            )}

            {orderedTypes.map((type) => (
              <div key={type}>
                <div className="px-3 py-1 text-xs font-semibold uppercase tracking-wider text-base-content/50 bg-base-200/50 sticky top-0">
                  {ACCOUNT_TYPE_LABELS[type] || type}
                </div>
                {groupedAccounts[type].map((account) => (
                  <div
                    key={account.id}
                    className={`px-3 py-2 cursor-pointer hover:bg-base-200 text-sm ${value === account.id ? 'bg-primary/10 font-medium text-primary' : ''}`}
                    onMouseDown={() => handleSelect(account.id)}
                  >
                    {account.name}
                  </div>
                ))}
              </div>
            ))}
          </div>

          {/* Create new account */}
          <div className="border-t border-base-300 p-1">
            <div
              className="px-3 py-2 cursor-pointer hover:bg-base-200 text-sm text-primary font-medium flex items-center gap-2 rounded"
              onMouseDown={handleCreateNew}
            >
              <i className="fa fa-plus text-xs"></i>
              {gettext('+ Create new account')}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AccountComboBox;
