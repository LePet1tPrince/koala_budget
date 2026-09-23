import React from 'react';

import Icon from '../common/Icon';

/* globals gettext */

/**
 * The server's guesses at where the difference comes from
 * (`apps/reconciliation/services/diagnose.py`). Hovering a hint highlights its
 * rows; a hint that names a single fix carries a one-click button for it.
 */
const DifferenceHints = ({ hints, onAction, onFocus }) => {
  if (!hints || hints.length === 0) return null;
  return (
    <section className="app-surface p-3" data-testid="difference-hints">
      <h2 className="text-sm font-semibold mb-2 flex items-center gap-2">
        <Icon name="search" className="w-4 h-4" />
        {gettext('The difference is probably one of these')}
      </h2>
      <ul className="space-y-2">
        {hints.map((hint, index) => (
          <li
            key={`${hint.kind}-${index}`}
            className="flex flex-wrap items-center gap-2 text-sm"
            onMouseEnter={() => onFocus(hint.line_ids)}
            onMouseLeave={() => onFocus([])}
            data-testid={`hint-${hint.kind}`}
          >
            <span className="grow">{hint.message}</span>
            {hint.action && (
              <button
                type="button"
                className="btn btn-outline btn-xs"
                onClick={() => {
                  onAction(hint);
                  onFocus([]);
                }}
                data-testid="hint-action"
              >
                {hint.action === 'tick' ? gettext('Tick it') : gettext('Untick')}
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
};

export default DifferenceHints;
