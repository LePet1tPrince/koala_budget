/* globals gettext */

import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { createPortal } from 'react-dom';

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
 *
 * The dropdown panel is rendered in a portal with fixed positioning so it is
 * not clipped by (or constrained to the width of) scrollable modal containers.
 */
const AccountComboBox = ({ allAccounts, value, onChange, onCreateNew }) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [menuPos, setMenuPos] = useState(null);
  const containerRef = useRef(null);
  const menuRef = useRef(null);
  const inputRef = useRef(null);

  const selectedAccount = useMemo(
    () => allAccounts.find((a) => a.id === value) || null,
    [allAccounts, value]
  );

  // Compute the dropdown position from the trigger button. Fixed positioning
  // lets the panel escape the modal's overflow clipping and width.
  const updatePosition = useCallback(() => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setMenuPos({
      left: rect.left,
      top: rect.bottom + 4,
      width: rect.width,
      // Space available below the trigger, so the panel can size to fit.
      maxHeight: Math.max(180, window.innerHeight - rect.bottom - 16),
    });
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    updatePosition();
    // Reposition while open so the panel tracks scroll/resize of any ancestor.
    const handle = () => updatePosition();
    window.addEventListener('resize', handle);
    window.addEventListener('scroll', handle, true);
    return () => {
      window.removeEventListener('resize', handle);
      window.removeEventListener('scroll', handle, true);
    };
  }, [open, updatePosition]);

  // Close dropdown when clicking outside (the panel lives in a portal, so we
  // must also exclude clicks landing inside it).
  useEffect(() => {
    const handleClickOutside = (e) => {
      const inTrigger = containerRef.current && containerRef.current.contains(e.target);
      const inMenu = menuRef.current && menuRef.current.contains(e.target);
      if (!inTrigger && !inMenu) {
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
        <span className={`truncate ${selectedAccount ? '' : 'text-base-content/50'}`}>
          {selectedAccount ? selectedAccount.name : gettext('-- Leave uncategorized --')}
          {selectedAccount && selectedAccount.institution_name && (
            <span className="text-base-content/50 font-normal"> · {selectedAccount.institution_name}</span>
          )}
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

      {/* Dropdown (portaled to body, fixed-positioned, escapes modal clipping) */}
      {open && menuPos && createPortal(
        <div
          ref={menuRef}
          className="fixed z-[1000] bg-base-100 border border-base-300 rounded-lg shadow-xl flex flex-col"
          style={{
            left: menuPos.left,
            top: menuPos.top,
            width: menuPos.width,
            minWidth: '16rem',
            maxHeight: menuPos.maxHeight,
          }}
        >
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
          <div className="overflow-y-auto flex-1">
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
                    className={`px-3 py-2 cursor-pointer hover:bg-base-200 text-sm flex items-center justify-between gap-2 ${value === account.id ? 'bg-primary/10 font-medium text-primary' : ''}`}
                    onMouseDown={() => handleSelect(account.id)}
                  >
                    <span className="truncate">{account.name}</span>
                    {account.institution_name && (
                      <span className="badge badge-ghost badge-sm whitespace-nowrap shrink-0" title={gettext('Held at')}>
                        <i className="fa fa-university text-[0.65rem] mr-1"></i>
                        {account.institution_name}
                      </span>
                    )}
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
        </div>,
        document.body
      )}
    </div>
  );
};

export default AccountComboBox;
