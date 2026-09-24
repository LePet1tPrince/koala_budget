/* globals gettext */

import React from 'react';

import Icon from '../common/Icon';

/**
 * The Export card and the Import card (§7 Phase 4 step 1).
 *
 * Export is a plain link, not a `fetch` — the browser's own download handling
 * (a `Content-Length`-backed file, resumable if the connection drops) is
 * exactly what a multi-megabyte zip wants, and nothing about the response
 * needs to be read back into React.
 */
const Step1Export = ({ exportUrl, uncategorizedCount, bankFeedUrl, onStartImport }) => (
  <div className="space-y-6">
    <div className="app-card space-y-3">
      <div className="flex items-start gap-3">
        <Icon name="download" className="mt-1 h-6 w-6 shrink-0 text-primary" />
        <div>
          <h2 className="text-lg font-semibold">{gettext('Export your books')}</h2>
          <p className="text-base-content/70 text-sm mt-1">
            {gettext(
              'Everything in this team — accounts, transactions, budgets, goals and reconciliation state — as a file you can open, keep, or load into another team.',
            )}
          </p>
        </div>
      </div>

      {uncategorizedCount > 0 && (
        <div className="alert alert-warning" data-testid="uncategorized-warning">
          <Icon name="triangle-alert" className="h-5 w-5 shrink-0" />
          <span>
            {gettext(
              '{count} transaction(s) in your Bank Feed have not been categorised yet. An export carries them as-is, but they will not show up anywhere else until you file them.',
            ).replace('{count}', uncategorizedCount)}
            {' '}
            <a href={bankFeedUrl} className="link link-primary">
              {gettext('Go to Bank Feed')}
            </a>
          </span>
        </div>
      )}

      <a href={exportUrl} className="btn btn-primary self-start" data-testid="export-button">
        <Icon name="download" className="h-4 w-4" />
        {gettext('Download export')}
      </a>
    </div>

    <div className="app-card space-y-3">
      <div className="flex items-start gap-3">
        <Icon name="upload" className="mt-1 h-6 w-6 shrink-0 text-warning" />
        <div>
          <h2 className="text-lg font-semibold">{gettext('Import into this team')}</h2>
          <p className="text-base-content/70 text-sm mt-1">
            {gettext(
              'Loading a Koala Budget export here replaces everything currently in this set of books. There is no merge — its existing accounts, transactions, budgets and goals are deleted first. Other sets of books in the team are not touched.',
            )}
          </p>
        </div>
      </div>
      <button type="button" className="btn btn-outline btn-warning self-start" onClick={onStartImport} data-testid="start-import-button">
        {gettext('Choose a file to import…')}
      </button>
    </div>
  </div>
);

export default Step1Export;
