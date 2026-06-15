import React, { useState, useEffect } from 'react';
import { Box, CircularProgress, Typography } from '@mui/material';

/* globals gettext */

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

const formatValue = (value) => {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? gettext('Yes') : gettext('No');
  if (typeof value === 'object' && value.name !== undefined) return value.name;
  return String(value);
};

const labelFor = (field) => (FIELD_LABELS[field] ? FIELD_LABELS[field]() : field);

/**
 * Group audit log entries that share the same user and second-precision timestamp
 * into a single visual event. This collapses the multiple rows that result from a
 * single edit (JournalEntry save + re-saves of its JournalLines).
 */
const groupLogs = (logs) => {
  const groups = [];
  for (const log of logs) {
    const tsKey = log.timestamp.slice(0, 19); // truncate to second
    const groupKey = `${log.user_display}::${tsKey}`;
    const last = groups[groups.length - 1];
    if (last && last.key === groupKey) {
      last.logs.push(log);
    } else {
      groups.push({ key: groupKey, user_display: log.user_display, timestamp: log.timestamp, logs: [log] });
    }
  }
  return groups;
};

/**
 * Flatten all changes from a group of logs into a single list of {field, before, after}.
 * CREATE / DELETE groups return a string label instead.
 */
const describeGroup = (group) => {
  const hasDelete = group.logs.some((l) => l.action === 'DELETE');
  const hasCreate = group.logs.some((l) => l.action === 'CREATE');

  if (hasDelete) return gettext('Deleted');
  if (hasCreate) return gettext('Created');

  // UPDATE: collect all field diffs across every log in the group
  const changes = [];
  for (const log of group.logs) {
    for (const [field, change] of Object.entries(log.changes || {})) {
      changes.push({
        field: labelFor(field),
        before: formatValue(change.before),
        after: formatValue(change.after),
      });
    }
  }
  return changes;
};

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
      .then((r) => {
        if (!r.ok) throw new Error(gettext('Failed to load history'));
        return r.json();
      })
      .then((data) => { if (!cancelled) setLogs(data); })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [teamSlug, journalEntryId]);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress size={28} />
      </Box>
    );
  }

  if (error) {
    return <Box sx={{ color: 'error.main', py: 2 }}>{error}</Box>;
  }

  if (!logs || logs.length === 0) {
    return (
      <Box sx={{ py: 4, textAlign: 'center', color: 'text.secondary' }}>
        {gettext('No changes recorded yet')}
      </Box>
    );
  }

  const groups = groupLogs(logs);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }} data-testid="transaction-history">
      {groups.map((group) => {
        const summary = describeGroup(group);
        return (
          <Box key={group.key} sx={{ borderLeft: '2px solid', borderColor: 'divider', pl: 2, pb: 1 }}>
            <Typography variant="caption" color="text.secondary">
              {new Date(group.timestamp).toLocaleString()} · {group.user_display}
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
