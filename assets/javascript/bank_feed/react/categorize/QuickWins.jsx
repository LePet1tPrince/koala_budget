/* globals gettext, interpolate, ngettext */
import React, { useEffect, useMemo, useRef, useState } from 'react';

import { formatMoney } from '../../../common/amount';
import { suggestionBadge } from './matching';
import { signedAmount, totalOf } from './queue';

/**
 * Every group with a confident guess, ticked, filed with one press: what is left
 * after it is the queue's hard part. Enter files the ticked ones; Escape goes
 * one by one instead.
 */
export default function QuickWins({ units, rowsById, accountsById, busy, onFile, onSkip }) {
  const [unticked, setUnticked] = useState(() => new Set());
  const fileRef = useRef(null);
  const ticked = useMemo(() => units.filter((u) => !unticked.has(u.key)), [units, unticked]);
  const rowCount = ticked.reduce((n, u) => n + u.ids.length, 0);

  useEffect(() => {
    fileRef.current?.focus({ preventScroll: true });
  }, []);

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      onSkip();
    }
  };

  return (
    <div
      className="card bg-base-100 border border-base-300 shadow-xl w-full max-w-2xl mx-auto"
      onKeyDown={handleKeyDown}
      data-testid="categorize-quick-wins"
    >
      <div className="card-body p-5 gap-3">
        <div>
          <h2 className="text-xl font-black">⚡ {gettext('Quick wins')}</h2>
          <p className="text-sm text-base-content/70">
            {gettext('Koala is sure about these. File them all at once, then sort the rest one by one.')}
          </p>
        </div>
        <ul className="max-h-[50vh] overflow-y-auto divide-y divide-base-200 -mx-1">
          {units.map((unit) => {
            const row = rowsById.get(unit.ids[0]);
            const suggestion = unit.suggestions[0];
            const category = accountsById[suggestion.category_id];
            const checked = !unticked.has(unit.key);
            return (
              <li key={unit.key}>
                <label className="flex items-center gap-3 px-1 py-2 cursor-pointer">
                  <input
                    type="checkbox"
                    className="checkbox checkbox-sm checkbox-primary"
                    checked={checked}
                    onChange={() =>
                      setUnticked((prev) => {
                        const next = new Set(prev);
                        if (next.has(unit.key)) next.delete(unit.key);
                        else next.add(unit.key);
                        return next;
                      })
                    }
                    data-testid="quick-win-check"
                  />
                  <span className="flex-1 min-w-0">
                    <span className="block font-semibold truncate">
                      {row?.merchant_name || row?.description}
                      {unit.ids.length > 1 && (
                        <span className="text-base-content/70 font-normal"> ×{unit.ids.length}</span>
                      )}
                    </span>
                    <span className="block text-xs text-base-content/70 truncate">
                      →{' '}
                      <span className="font-medium text-base-content">
                        {category?.name ?? suggestion.category_name}
                      </span>
                      {' · '}
                      {suggestionBadge(suggestion)}
                    </span>
                  </span>
                  <span
                    className={`text-sm font-semibold tabular-nums shrink-0 ${
                      signedAmount(row) > 0 ? 'text-error' : 'text-success'
                    }`}
                  >
                    {formatMoney(totalOf(unit.ids, rowsById))}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button type="button" className="btn btn-ghost" onClick={onSkip} data-testid="quick-wins-skip">
            {gettext('One by one instead')} <kbd className="kbd kbd-xs">esc</kbd>
          </button>
          <button
            ref={fileRef}
            type="button"
            className="btn btn-primary"
            disabled={busy || ticked.length === 0}
            onClick={() => onFile(ticked)}
            data-testid="quick-wins-file"
          >
            {busy && <span className="loading loading-spinner loading-xs" />}
            {interpolate(ngettext('File %s transaction', 'File %s transactions', rowCount), [rowCount])}
            <kbd className="kbd kbd-xs">↵</kbd>
          </button>
        </div>
      </div>
    </div>
  );
}
