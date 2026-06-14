import React, { useState, useEffect } from 'react';
import { Box, CircularProgress, Typography } from '@mui/material';

/* globals gettext */

// Human-readable labels for the snapshot/diff fields produced by the backend audit signals.
const FIELD_LABELS = {
  entry_date: () => gettext('Date'),
  description: () => gettext('Description'),
  status: () => gettext('Status'),
  payee: () => gettext('Payee'),
  account: () => gettext('Category'),
  dr_amount: () => gettext('Debit'),
  cr_amount: () => gettext('Credit'),
  is_reconciled: () => gettext('Reconciled'),
  is_cleared: () => gettext('Cleared'),
};

// Render a stored value into a display string. FK snapshots are {id, name}; booleans
// become Yes/No; null becomes an em dash.
const formatValue = (value) => {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? gettext('Yes') : gettext('No');
  if (typeof value === 'object' && value.name !== undefined) return value.name;
  return String(value);
};

const labelFor = (field) => (FIELD_LABELS[field] ? FIELD_LABELS[field]() : field);

// Build a one-line summary for each audit log entry.
const describeLog = (log) => {
  if (log.action === 'CREATE') {
    return gettext('Created');
  }
  if (log.action === 'DELETE') {
    return gettext('Deleted');
  }
  // UPDATE: changes is {field: {before, after}}
  return Object.entries(log.changes || {}).map(([field, change]) => ({
    field: labelFor(field),
    before: formatValue(change.before),
    after: formatValue(change.after),
  }));
};

const sourceLabel = (sourceModel) =>
  sourceModel === 'JournalLine' ? gettext('Line') : gettext('Entry');

/**
 * TransactionHistory - lazy-loads and renders the audit history timeline for a
 * journal entry. Calls GET /a/{teamSlug}/journal/api/journal-entries/{id}/audit/.
 */
const TransactionHistory = ({ teamSlug, journalEntryId }) => {
  const [logs, setLogs] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!journalEntryId || !teamSlug) {
      setLogs([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`/a/${teamSlug}/journal/api/journal-entries/${journalEntryId}/audit/`, {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    })
      .then((response) => {
        if (!response.ok) throw new Error(gettext('Failed to load history'));
        return response.json();
      })
      .then((data) => {
        if (!cancelled) setLogs(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [teamSlug, journalEntryId]);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress size={28} />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ color: 'error.main', py: 2 }}>
        {error}
      </Box>
    );
  }

  if (!logs || logs.length === 0) {
    return (
      <Box sx={{ py: 4, textAlign: 'center', color: 'text.secondary' }}>
        {gettext('No changes recorded yet')}
      </Box>
    );
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }} data-testid="transaction-history">
      {logs.map((log) => {
        const summary = describeLog(log);
        return (
          <Box
            key={log.id}
            sx={{ borderLeft: '2px solid', borderColor: 'divider', pl: 2, pb: 1 }}
          >
            <Typography variant="caption" color="text.secondary">
              {new Date(log.timestamp).toLocaleString()} · {log.user_display} · {sourceLabel(log.source_model)}
            </Typography>
            {Array.isArray(summary) ? (
              <Box component="ul" sx={{ m: 0, pl: 2 }}>
                {summary.map((c, i) => (
                  <li key={i}>
                    <Typography variant="body2" component="span">
                      <strong>{c.field}:</strong> {c.before} → {c.after}
                    </Typography>
                  </li>
                ))}
              </Box>
            ) : (
              <Typography variant="body2">{summary}</Typography>
            )}
          </Box>
        );
      })}
    </Box>
  );
};

export default TransactionHistory;
