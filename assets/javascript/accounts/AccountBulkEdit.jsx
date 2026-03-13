import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { DataGrid, renderTextEditor } from 'react-data-grid';
import Cookies from 'js-cookie';
import 'react-data-grid/lib/styles.css';

/* globals gettext */

// ── helpers ──────────────────────────────────────────────────────────────────

function getCsrf() {
  return Cookies.get('csrftoken') || '';
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrf(),
      ...options.headers,
    },
    ...options,
  });
  return response;
}

// Select editor for account_group column
function GroupSelectEditor({ row, column, onRowChange, onClose, accountGroups }) {
  return (
    <select
      autoFocus
      className="w-full h-full border-0 bg-base-100 text-sm"
      value={row.account_group ?? ''}
      onChange={(e) => {
        const groupId = e.target.value ? parseInt(e.target.value, 10) : null;
        const group = accountGroups.find((g) => g.id === groupId);
        onRowChange(
          {
            ...row,
            account_group: groupId,
            account_group_name: group ? group.name : '',
            account_type: group ? group.account_type : '',
          },
          true
        );
      }}
      onBlur={() => onClose()}
    >
      <option value="">— select —</option>
      {accountGroups.map((g) => (
        <option key={g.id} value={g.id}>
          {g.name} ({g.account_type})
        </option>
      ))}
    </select>
  );
}

// Checkbox renderer for has_feed column
function CheckboxFormatter({ row, column, onRowChange, isCellSelected }) {
  return (
    <input
      type="checkbox"
      className="checkbox checkbox-sm"
      checked={row.has_feed ?? false}
      onChange={(e) => onRowChange({ ...row, has_feed: e.target.checked })}
      onClick={(e) => e.stopPropagation()}
    />
  );
}

// ── main component ────────────────────────────────────────────────────────────

export default function AccountBulkEdit({ apiUrls }) {
  const [rows, setRows] = useState([]);
  const [accountGroups, setAccountGroups] = useState([]);
  const [dirtyIds, setDirtyIds] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  // Import modal state
  const [importOpen, setImportOpen] = useState(false);
  const [importPreview, setImportPreview] = useState(null);
  const [importErrors, setImportErrors] = useState([]);
  const [importLoading, setImportLoading] = useState(false);

  const fileInputRef = useRef(null);

  // ── load data ──────────────────────────────────────────────────────────────

  useEffect(() => {
    setLoading(true);
    apiFetch(apiUrls.data)
      .then((r) => r.json())
      .then(({ accounts, account_groups }) => {
        setRows(accounts.map((a) => ({ ...a, _isNew: false })));
        setAccountGroups(account_groups);
        setLoading(false);
      })
      .catch(() => {
        setError(gettext('Failed to load accounts.'));
        setLoading(false);
      });
  }, []);

  // ── columns ────────────────────────────────────────────────────────────────

  const columns = useMemo(
    () => [
      {
        key: 'account_number',
        name: gettext('Number'),
        width: 110,
        renderEditCell: renderTextEditor,
      },
      {
        key: 'name',
        name: gettext('Name'),
        renderEditCell: renderTextEditor,
      },
      {
        key: 'account_group_name',
        name: gettext('Account Group'),
        width: 220,
        renderEditCell: (props) => (
          <GroupSelectEditor {...props} accountGroups={accountGroups} />
        ),
      },
      {
        key: 'account_type',
        name: gettext('Type'),
        width: 110,
        renderCell: ({ row }) => (
          <span className="text-xs text-gray-500">{row.account_type}</span>
        ),
      },
      {
        key: 'has_feed',
        name: gettext('Has Feed'),
        width: 90,
        renderCell: ({ row, column, onRowChange }) => (
          <CheckboxFormatter row={row} column={column} onRowChange={onRowChange} />
        ),
        renderEditCell: ({ row, column, onRowChange }) => (
          <CheckboxFormatter row={row} column={column} onRowChange={onRowChange} />
        ),
      },
    ],
    [accountGroups]
  );

  // ── row change handler ─────────────────────────────────────────────────────

  const onRowsChange = useCallback(
    (updatedRows, { indexes }) => {
      setRows(updatedRows);
      setDirtyIds((prev) => {
        const next = new Set(prev);
        for (const idx of indexes) {
          const row = updatedRows[idx];
          // New rows don't have an id yet; track by a temp key
          next.add(row.id ?? `new-${idx}`);
        }
        return next;
      });
    },
    []
  );

  // ── row class for dirty highlighting ──────────────────────────────────────

  const rowClass = useCallback(
    (row) => {
      if (row._isNew) return 'bg-green-50';
      if (dirtyIds.has(row.id)) return 'bg-yellow-50';
      return undefined;
    },
    [dirtyIds]
  );

  // ── add new row ───────────────────────────────────────────────────────────

  const addRow = useCallback(() => {
    const tempId = `new-${Date.now()}`;
    const newRow = {
      id: null,
      _tempId: tempId,
      _isNew: true,
      account_number: '',
      name: '',
      account_group: null,
      account_group_name: '',
      account_type: '',
      has_feed: false,
    };
    setRows((prev) => [...prev, newRow]);
    setDirtyIds((prev) => new Set([...prev, tempId]));
  }, []);

  // ── save ──────────────────────────────────────────────────────────────────

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSuccessMsg(null);

    const payload = rows.map((row) => ({
      id: row.id ?? undefined,
      name: row.name,
      account_number: row.account_number,
      account_group: row.account_group,
      has_feed: row.has_feed,
    }));

    const response = await apiFetch(apiUrls.save, {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (!response.ok) {
      setSaving(false);
      setError(data.error || gettext('Save failed. Please check your entries.'));
      return;
    }

    setRows(data.accounts.map((a) => ({ ...a, _isNew: false })));
    setDirtyIds(new Set());
    setSaving(false);
    setSuccessMsg(gettext('Changes saved successfully.'));
    setTimeout(() => setSuccessMsg(null), 3000);
  }, [rows, apiUrls.save]);

  // ── CSV export ────────────────────────────────────────────────────────────

  const exportCsv = useCallback(() => {
    window.location.href = apiUrls.export_csv;
  }, [apiUrls.export_csv]);

  // ── CSV import ────────────────────────────────────────────────────────────

  const openImport = () => {
    setImportPreview(null);
    setImportErrors([]);
    setImportOpen(true);
  };

  const handleFileSelect = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setImportLoading(true);
    setImportErrors([]);

    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(apiUrls.import_csv, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrf() },
      body: formData,
    });
    const data = await response.json();
    setImportLoading(false);

    if (!response.ok) {
      setImportErrors([{ row: '-', errors: [data.error] }]);
      return;
    }

    setImportPreview(data.valid);
    if (data.errors?.length) {
      setImportErrors(data.errors);
    }
  };

  const confirmImport = async () => {
    if (!importPreview?.length) return;

    setSaving(true);
    setImportOpen(false);

    const payload = importPreview.map((item) => ({
      id: item.id,
      name: item.name,
      account_number: item.account_number,
      account_group: item.account_group,
      has_feed: item.has_feed,
    }));

    const response = await apiFetch(apiUrls.save, {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    const data = await response.json();
    setSaving(false);

    if (!response.ok) {
      setError(data.error || gettext('Import failed.'));
      return;
    }

    setRows(data.accounts.map((a) => ({ ...a, _isNew: false })));
    setDirtyIds(new Set());
    setSuccessMsg(gettext('Import completed successfully.'));
    setTimeout(() => setSuccessMsg(null), 3000);
  };

  // ── render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <span className="loading loading-spinner loading-lg" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Breadcrumb */}
      <nav aria-label="breadcrumbs">
        <ol className="pg-breadcrumbs">
          <li>
            <a href="../" className="pg-breadcrumb-link">
              {gettext('Accounts')}
            </a>
          </li>
          <li className="pg-breadcrumb-active" aria-current="page">
            {gettext('Bulk Edit')}
          </li>
        </ol>
      </nav>

      {/* Toolbar */}
      <section className="app-card">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
          <h3 className="pg-subtitle">{gettext('Bulk Edit Accounts')}</h3>
          <div className="flex flex-wrap gap-2">
            <button className="pg-button-secondary pg-button-sm" onClick={exportCsv}>
              {gettext('Export CSV')}
            </button>
            <button className="pg-button-secondary pg-button-sm" onClick={openImport}>
              {gettext('Import CSV')}
            </button>
            <button className="pg-button-secondary pg-button-sm" onClick={addRow}>
              + {gettext('Add Row')}
            </button>
            <button
              className="pg-button-primary pg-button-sm"
              onClick={save}
              disabled={saving || dirtyIds.size === 0}
            >
              {saving ? gettext('Saving…') : gettext('Save Changes')}
              {!saving && dirtyIds.size > 0 && (
                <span className="ml-1 badge badge-sm badge-warning">{dirtyIds.size}</span>
              )}
            </button>
          </div>
        </div>

        {/* Alert messages */}
        {error && (
          <div className="alert alert-error mb-3">
            <span>{error}</span>
          </div>
        )}
        {successMsg && (
          <div className="alert alert-success mb-3">
            <span>{successMsg}</span>
          </div>
        )}

        {/* Hint */}
        <p className="text-sm text-gray-500 mb-3">
          {gettext(
            'Click any cell to edit. Paste rows copied from Excel directly into the grid. Yellow rows have unsaved changes.'
          )}
        </p>

        {/* Grid */}
        <div className="border border-base-300 rounded-lg overflow-hidden">
          <DataGrid
            columns={columns}
            rows={rows}
            onRowsChange={onRowsChange}
            rowClass={rowClass}
            className="rdg-light"
            style={{ blockSize: 'auto', minHeight: 300, maxHeight: '70vh' }}
          />
        </div>
      </section>

      {/* Import modal */}
      {importOpen && (
        <dialog className="modal modal-open">
          <div className="modal-box max-w-2xl">
            <h3 className="font-bold text-lg mb-4">{gettext('Import Accounts from CSV')}</h3>

            <p className="text-sm text-gray-600 mb-3">
              {gettext(
                'Upload a CSV file with columns: account_number, name, account_group, has_feed. ' +
                  'Rows with a matching id will be updated; rows without an id will be created.'
              )}
            </p>

            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              className="file-input file-input-bordered w-full mb-4"
              onChange={handleFileSelect}
            />

            {importLoading && (
              <div className="flex justify-center py-4">
                <span className="loading loading-spinner" />
              </div>
            )}

            {importErrors.length > 0 && (
              <div className="alert alert-error mb-3">
                <div>
                  <p className="font-semibold mb-1">{gettext('Errors found:')}</p>
                  <ul className="list-disc list-inside text-sm">
                    {importErrors.map((e, i) => (
                      <li key={i}>
                        {gettext('Row')} {e.row}: {(e.errors || []).join(', ')}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            {importPreview && importPreview.length > 0 && (
              <div className="overflow-x-auto mb-4">
                <p className="text-sm font-semibold mb-2">
                  {gettext('Preview')} ({importPreview.length}{' '}
                  {importPreview.length === 1 ? gettext('row') : gettext('rows')}):
                </p>
                <table className="table table-xs table-zebra w-full">
                  <thead>
                    <tr>
                      <th>{gettext('Action')}</th>
                      <th>{gettext('Number')}</th>
                      <th>{gettext('Name')}</th>
                      <th>{gettext('Group')}</th>
                      <th>{gettext('Has Feed')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {importPreview.map((row, i) => (
                      <tr key={i}>
                        <td>
                          <span
                            className={`badge badge-sm ${
                              row.action === 'create' ? 'badge-success' : 'badge-info'
                            }`}
                          >
                            {row.action}
                          </span>
                        </td>
                        <td>{row.account_number}</td>
                        <td>{row.name}</td>
                        <td>{row.account_group_name}</td>
                        <td>{row.has_feed ? '✓' : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="modal-action">
              <button className="btn" onClick={() => setImportOpen(false)}>
                {gettext('Cancel')}
              </button>
              {importPreview && importPreview.length > 0 && (
                <button className="btn btn-primary" onClick={confirmImport}>
                  {gettext('Import')} {importPreview.length}{' '}
                  {importPreview.length === 1 ? gettext('account') : gettext('accounts')}
                </button>
              )}
            </div>
          </div>
          <form method="dialog" className="modal-backdrop">
            <button onClick={() => setImportOpen(false)}>close</button>
          </form>
        </dialog>
      )}
    </div>
  );
}
