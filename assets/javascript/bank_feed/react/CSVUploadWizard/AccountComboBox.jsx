/* globals gettext */

import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { createPortal } from 'react-dom';

// Build a flat list of selectable options (null = uncategorized, then accounts in order)
const buildFlatOptions = (orderedTypes, groupedAccounts) => {
  const opts = [{ id: null, label: gettext('-- Leave uncategorized --') }];
  orderedTypes.forEach((type) => {
    groupedAccounts[type].forEach((account) => {
      opts.push({ id: account.id, label: account.name });
    });
  });
  return opts;
};

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
  const [focusedIndex, setFocusedIndex] = useState(0);
  const containerRef = useRef(null);
  const menuRef = useRef(null);
  const inputRef = useRef(null);
  const triggerRef = useRef(null);
  const optionRefs = useRef([]);

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

  const flatOptions = useMemo(
    () => buildFlatOptions(orderedTypes, groupedAccounts),
    [orderedTypes, groupedAccounts]
  );

  // Reset focused index when search changes or dropdown opens
  useEffect(() => {
    if (open) {
      const currentIdx = flatOptions.findIndex((o) => o.id === value);
      setFocusedIndex(currentIdx >= 0 ? currentIdx : 0);
    }
  }, [open, search]); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll focused option into view
  useEffect(() => {
    if (open && optionRefs.current[focusedIndex]) {
      optionRefs.current[focusedIndex].scrollIntoView({ block: 'nearest' });
    }
  }, [focusedIndex, open]);

  const handleSelect = (accountId, fromKeyboard = false) => {
    onChange(accountId);
    setOpen(false);
    setSearch('');
    if (fromKeyboard && triggerRef.current) {
      // Return focus to trigger so Tab moves to the next card's button
      triggerRef.current.focus();
    }
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

  const handleSearchKeyDown = (e) => {
    if (e.key === 'Escape') {
      setOpen(false);
      triggerRef.current && triggerRef.current.focus();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setFocusedIndex((i) => Math.min(i + 1, flatOptions.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setFocusedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (flatOptions[focusedIndex] !== undefined) {
        handleSelect(flatOptions[focusedIndex].id, true);
      }
    } else if (e.key === 'Tab') {
      // Close dropdown and let Tab move to next focusable element naturally
      setOpen(false);
      setSearch('');
    }
  };

  return (
    <div ref={containerRef} className="relative w-full">
      {/* Trigger button */}
      <button
        ref={triggerRef}
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
              onKeyDown={handleSearchKeyDown}
            />
          </div>

          {/* Options list */}
          <div className="overflow-y-auto flex-1">
            {/* Leave uncategorized option (flat index 0) */}
            <div
              ref={(el) => { optionRefs.current[0] = el; }}
              className={`px-3 py-2 cursor-pointer text-sm text-base-content/60 italic ${!value ? 'bg-primary/10 font-medium' : ''} ${focusedIndex === 0 ? 'bg-base-300' : 'hover:bg-base-200'}`}
              onMouseDown={() => handleSelect(null)}
            >
              {gettext('-- Leave uncategorized --')}
            </div>

            {!hasResults && (
              <div className="px-3 py-3 text-sm text-base-content/50 text-center">
                {gettext('No accounts found')}
              </div>
            )}

            {(() => {
              let flatIdx = 1;
              return orderedTypes.map((type) => (
                <div key={type}>
                  <div className="px-3 py-1 text-xs font-semibold uppercase tracking-wider text-base-content/50 bg-base-200/50 sticky top-0">
                    {ACCOUNT_TYPE_LABELS[type] || type}
                  </div>
                  {groupedAccounts[type].map((account) => {
                    const idx = flatIdx++;
                    return (
                      <div
                        key={account.id}
                        ref={(el) => { optionRefs.current[idx] = el; }}
                        className={`px-3 py-2 cursor-pointer text-sm flex items-center justify-between gap-2 ${value === account.id ? 'bg-primary/10 font-medium text-primary' : ''} ${focusedIndex === idx ? 'bg-base-300' : 'hover:bg-base-200'}`}
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
                    );
                  })}
                </div>
              ));
            })()}
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
