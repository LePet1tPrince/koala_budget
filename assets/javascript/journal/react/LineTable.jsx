/* globals gettext */
import React, { useMemo, useState } from 'react';
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table';

import DateRangePicker from '../../common/DateRangePicker';
import { formatCurrency } from '../../utilities/currency';

/**
 * LineTable component - displays and edits lines using TanStack Table
 */
const LineTable = ({
  lines,
  selectedAccount,
  allAccounts,
  allPayees,
  onAdd,
  onUpdate,
  onDelete,
}) => {
  const [sorting, setSorting] = useState([]);
  const [editingRow, setEditingRow] = useState(null);
  const [isAdding, setIsAdding] = useState(false);
  const [newLine, setNewLine] = useState({
    date: new Date().toISOString().split('T')[0],
    account: selectedAccount?.account_id || '',
    category: '',
    inflow: '',
    outflow: '',
    description: '',
    payee: '',
    isCleared: false,
    isReconciled: false,
  });

  // Date range filter state (YYYY-MM-DD strings)
  const [filterStart, setFilterStart] = useState('');
  const [filterEnd, setFilterEnd] = useState('');


  // Format date for display
  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleDateString();
  };

  // Format date for input field (YYYY-MM-DD)
  const formatDateForInput = (dateVal) => {
    if (!dateVal) return '';
    const date = dateVal instanceof Date ? dateVal : new Date(dateVal);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  // Get account name by ID
  const getAccountName = (accountId) => {
    const account = allAccounts.find((a) => a.account_id === accountId);
    return account ? account.name : '';
  };

  // Get payee name by ID
  const getPayeeName = (payeeId) => {
    if (!payeeId) return '';
    const payee = allPayees.find((p) => p.id === payeeId);
    return payee ? payee.name : '';
  };

  // Handle edit start
  const handleEditStart = (row) => {
    setEditingRow(row.id);
  };

  // Handle edit save (called from RowEditor with updated values)
  const handleEditSave = async (rowId, updatedData) => {
    try {
      await onUpdate(rowId, updatedData);
      setEditingRow(null);
    } catch (error) {
      console.error('Failed to update line:', error);
      alert(gettext('Failed to update line'));
    }
  };

  // Handle edit cancel
  const handleEditCancel = () => {
    setEditingRow(null);
  };

  // RowEditor component: local state for editing a single row to avoid
  // recreating column definitions on every keystroke.
  const RowEditor = ({ original }) => {
    const [local, setLocal] = useState({
      date: formatDateForInput(original.date),
      account: original.account,
      category: original.category,
      inflow: original.inflow ?? '',
      outflow: original.outflow ?? '',
      description: original.description ?? '',
      payee: original.payee ?? '',
      isCleared: !!original.isCleared,
      isReconciled: !!original.isReconciled,
    });

    return (
      <>
        <td>
          <input
            type="date"
            className="input input-sm input-bordered w-full"
            value={local.date}
            onChange={(e) => setLocal({ ...local, date: e.target.value })}
          />
        </td>
        <td>
          <select
            className="select select-sm select-bordered w-full"
            value={local.category}
            onChange={(e) => setLocal({ ...local, category: parseInt(e.target.value) })}
          >
            <option value="">{gettext('Select category')}</option>
            {allAccounts.map((account) => (
              <option key={account.account_id} value={account.account_id}>
                {account.account_number} - {account.name}
              </option>
            ))}
          </select>
        </td>
        <td>
          <input
            type="number"
            step="0.01"
            className="input input-sm input-bordered w-full"
            value={local.inflow}
            onChange={(e) => setLocal((p) => ({ ...p, inflow: e.target.value }))}
            onBlur={() => {
              if (local.inflow && parseFloat(local.inflow) > 0) {
                setLocal((p) => ({ ...p, outflow: '0' }));
              }
            }}
          />
        </td>
        <td>
          <input
            type="number"
            step="0.01"
            className="input input-sm input-bordered w-full"
            value={local.outflow}
            onChange={(e) => setLocal((p) => ({ ...p, outflow: e.target.value }))}
            onBlur={() => {
              if (local.outflow && parseFloat(local.outflow) > 0) {
                setLocal((p) => ({ ...p, inflow: '0' }));
              }
            }}
          />
        </td>
        <td>
          <input
            type="text"
            className="input input-sm input-bordered w-full"
            value={local.description}
            onChange={(e) => setLocal({ ...local, description: e.target.value })}
          />
        </td>
        <td>
          <select
            className="select select-sm select-bordered w-full"
            value={local.payee}
            onChange={(e) => setLocal({ ...local, payee: e.target.value ? parseInt(e.target.value) : '' })}
          >
            <option value="">{gettext('None')}</option>
            {allPayees.map((payee) => (
              <option key={payee.id} value={payee.id}>
                {payee.name}
              </option>
            ))}
          </select>
        </td>
        <td className="text-center">
          <input
            type="checkbox"
            className="checkbox checkbox-sm"
            checked={!!local.isCleared}
            onChange={(e) => setLocal({ ...local, isCleared: e.target.checked })}
          />
        </td>
        <td className="text-center">
          <input
            type="checkbox"
            className="checkbox checkbox-sm"
            checked={!!local.isReconciled}
            onChange={(e) => setLocal({ ...local, isReconciled: e.target.checked })}
          />
        </td>
        <td>
          <div className="flex gap-1">
            <button
              className="btn btn-sm btn-success"
              onClick={() => handleEditSave(original.lineId, local)}
            >
              <i className="fa fa-check" />
            </button>
            <button
              className="btn btn-sm btn-ghost"
              onClick={handleEditCancel}
            >
              <i className="fa fa-times" />
            </button>
          </div>
        </td>
      </>
    );
  };

  // Handle add line
  const handleAddLine = async () => {
    // Validate the data before sending
    if (!newLine.date) {
      alert(gettext('Date is required'));
      return;
    }
    if (!newLine.account) {
      alert(gettext('Account is required'));
      return;
    }
    if (!newLine.category) {
      alert(gettext('Category is required'));
      return;
    }
    // Validate that exactly one of inflow or outflow is specified
    const hasInflow = newLine.inflow && parseFloat(newLine.inflow) > 0;
    const hasOutflow = newLine.outflow && parseFloat(newLine.outflow) > 0;
    if (!hasInflow && !hasOutflow) {
      alert(gettext('Either inflow or outflow is required'));
      return;
    }
    if (hasInflow && hasOutflow) {
      alert(gettext('Cannot have both inflow and outflow'));
      return;
    }

    try {
      await onAdd(newLine);
      setIsAdding(false);
      setNewLine({
        date: new Date().toISOString().split('T')[0],
        account: selectedAccount?.account_id || '',
        category: '',
        inflow: '',
        outflow: '',
        description: '',
        payee: '',
        isCleared: false,
        isReconciled: false,
      });
    } catch (error) {
      console.error('Failed to add line:', error);
      alert(gettext('Failed to add line'));
    }
  };

  // Handle delete
  const handleDelete = async (row) => {
      if (confirm(gettext('Are you sure you want to delete this line?'))) {
      try {
        await onDelete(row.original.lineId);
      } catch (error) {
        console.error('Failed to delete line:', error);
        alert(gettext('Failed to delete line'));
      }
    }
  };

  // Define columns
  const columns = useMemo(
    () => [
      {
        accessorKey: 'date',
        header: gettext('Date'),
        cell: ({ getValue }) => formatDate(getValue()),
      },
      {
        accessorKey: 'category',
        header: gettext('Category'),
        cell: ({ getValue }) => {
          const categoryId = getValue();
          const account = allAccounts.find((a) => a.account_id === categoryId);
          return account ? `${account.account_number} - ${account.name}` : '';
        },
      },
      {
        accessorKey: 'inflow',
        header: gettext('Inflow'),
        cell: ({ getValue }) => {
          const value = getValue();
          return value && parseFloat(value) > 0 ? formatCurrency(value) : '';
        },
      },
      {
        accessorKey: 'outflow',
        header: gettext('Outflow'),
        cell: ({ getValue }) => {
          const value = getValue();
          return value && parseFloat(value) > 0 ? formatCurrency(value) : '';
        },
      },
      {
        accessorKey: 'description',
        header: gettext('Description'),
        cell: ({ getValue }) => getValue(),
      },
      {
        accessorKey: 'payee',
        header: gettext('Payee'),
        cell: ({ getValue }) => getPayeeName(getValue()),
      },
      {
        accessorKey: 'isCleared',
        header: gettext('Cleared'),
        cell: ({ getValue }) => (getValue() ? <i className="fa fa-check text-success"></i> : ''),
      },
      {
        accessorKey: 'isReconciled',
        header: gettext('Reconciled'),
        cell: ({ getValue }) => (getValue() ? <i className="fa fa-check text-success"></i> : ''),
      },
      {
        id: 'actions',
        header: gettext('Actions'),
        cell: ({ row }) => (
          <div className="flex gap-1">
            <button
              className="btn btn-sm btn-ghost"
              onClick={() => handleEditStart(row)}
            >
              <i className="fa fa-edit"></i>
            </button>
            <button
              className="btn btn-sm btn-error btn-ghost"
              onClick={() => handleDelete(row)}
            >
              <i className="fa fa-trash"></i>
            </button>
          </div>
        ),
      },
    ],
    [allAccounts, allPayees]
  );

  // Create table instance
  // Filter lines by selected date range before passing to the table
  const filteredLines = useMemo(() => {
    if (!filterStart && !filterEnd) return lines;
    const s = filterStart ? new Date(filterStart) : null;
    const e = filterEnd ? new Date(filterEnd) : null;
    // make end of day inclusive
    const eInclusive = e ? new Date(e.getFullYear(), e.getMonth(), e.getDate(), 23, 59, 59, 999) : null;
    return lines.filter((l) => {
      if (!l.date) return false;
      const d = new Date(l.date);
      if (s && d < s) return false;
      if (eInclusive && d > eInclusive) return false;
      return true;
    });
  }, [lines, filterStart, filterEnd]);

  const table = useReactTable({
    data: filteredLines,
    columns,
    getRowId: (row) => row.lineId,
    state: {
      sorting,
    },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: {
        pageSize: 10,
      },
    },
  });

  if (!selectedAccount) {
    return (
      <div className="alert alert-info">
        <i className="fa fa-info-circle"></i>
        <span>{gettext('Please select an account to view lines')}</span>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <DateRangePicker
            startDate={filterStart}
            endDate={filterEnd}
            onApply={(s, e) => {
              setFilterStart(s);
              setFilterEnd(e);
            }}
          />
        </div>
        <div className="text-sm text-gray-500">{filteredLines.length} {gettext('lines')}</div>
      </div>
      {/* Add Line Button */}
      {!isAdding && (
        <button
          className="btn btn-primary"
          onClick={() => setIsAdding(true)}
        >
          <i className="fa fa-plus"></i>
          {gettext('Add Line')}
        </button>
      )}

      {/* Add Line Form */}
      {isAdding && (
        <div className="card bg-base-200 shadow-md">
          <div className="card-body">
            <h3 className="card-title">{gettext('New Line')}</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              <div className="form-control">
                <label className="label">
                  <span className="label-text">{gettext('Date')}</span>
                </label>
                <input
                  type="date"
                  className="input input-bordered"
                  value={newLine.date}
                  onChange={(e) => setNewLine({ ...newLine, date: e.target.value })}
                />
              </div>
              <div className="form-control">
                <label className="label">
                  <span className="label-text">{gettext('Category')}</span>
                </label>
                <select
                  className="select select-bordered"
                  value={newLine.category}
                  onChange={(e) => setNewLine({ ...newLine, category: parseInt(e.target.value) })}
                >
                  <option value="">{gettext('Select category')}</option>
                  {allAccounts.map((account) => (
                    <option key={account.account_id} value={account.account_id}>
                      {account.account_number} - {account.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-control">
                <label className="label">
                  <span className="label-text">{gettext('Inflow')}</span>
                </label>
                <input
                  type="number"
                  step="0.01"
                  className="input input-bordered"
                  defaultValue={newLine.inflow}
                  onBlur={(e) => {
                    const newValue = e.target.value;
                    // Only clear outflow if inflow has a value
                    if (newValue && parseFloat(newValue) > 0) {
                      setNewLine({ ...newLine, inflow: newValue, outflow: '0' });
                    } else {
                      setNewLine({ ...newLine, inflow: newValue });
                    }
                  }}
                />
              </div>
              <div className="form-control">
                <label className="label">
                  <span className="label-text">{gettext('Outflow')}</span>
                </label>
                <input
                  type="number"
                  step="0.01"
                  className="input input-bordered"
                  defaultValue={newLine.outflow}
                  onBlur={(e) => {
                    const newValue = e.target.value;
                    // Only clear inflow if outflow has a value
                    if (newValue && parseFloat(newValue) > 0) {
                      setNewLine({ ...newLine, outflow: newValue, inflow: '0' });
                    } else {
                      setNewLine({ ...newLine, outflow: newValue });
                    }
                  }}
                />
              </div>
              <div className="form-control md:col-span-2">
                <label className="label">
                  <span className="label-text">{gettext('Description')}</span>
                </label>
                <input
                  type="text"
                  className="input input-bordered"
                  value={newLine.description}
                  onChange={(e) => setNewLine({ ...newLine, description: e.target.value })}
                />
              </div>
              <div className="form-control">
                <label className="label">
                  <span className="label-text">{gettext('Payee')}</span>
                </label>
                <select
                  className="select select-bordered"
                  value={newLine.payee}
                  onChange={(e) => setNewLine({ ...newLine, payee: e.target.value ? parseInt(e.target.value) : null })}
                >
                  <option value="">{gettext('None')}</option>
                  {allPayees.map((payee) => (
                    <option key={payee.id} value={payee.id}>
                      {payee.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-control">
                <label className="label cursor-pointer">
                  <span className="label-text">{gettext('Cleared')}</span>
                  <input
                    type="checkbox"
                    className="checkbox"
                    checked={newLine.isCleared}
                    onChange={(e) => setNewLine({ ...newLine, isCleared: e.target.checked })}
                  />
                </label>
              </div>
              <div className="form-control">
                <label className="label cursor-pointer">
                  <span className="label-text">{gettext('Reconciled')}</span>
                  <input
                    type="checkbox"
                    className="checkbox"
                    checked={newLine.isReconciled}
                    onChange={(e) => setNewLine({ ...newLine, isReconciled: e.target.checked })}
                  />
                </label>
              </div>
            </div>
            <div className="card-actions justify-end mt-4">
              <button className="btn btn-ghost" onClick={() => setIsAdding(false)}>
                {gettext('Cancel')}
              </button>
              <button className="btn btn-primary" onClick={handleAddLine}>
                {gettext('Save')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Lines Table */}
      <div className="overflow-x-auto">
        <table className="table table-zebra w-full">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id}>
                    {header.isPlaceholder ? null : (
                      <div
                        className={header.column.getCanSort() ? 'cursor-pointer select-none' : ''}
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {{
                          asc: ' 🔼',
                          desc: ' 🔽',
                        }[header.column.getIsSorted()] ?? null}
                      </div>
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="text-center py-8 text-base-content/60">
                  {gettext('No lines found')}
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => {
                if (editingRow === row.id) {
                  return (
                    <tr key={row.id}>
                      <RowEditor original={row.original} />
                    </tr>
                  );
                }
                return (
                  <tr key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                    ))}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {table.getPageCount() > 1 && (
        <div className="flex items-center justify-between">
          <div className="text-sm text-base-content/70">
            {gettext('Page')} {table.getState().pagination.pageIndex + 1} {gettext('of')} {table.getPageCount()}
          </div>
          <div className="join">
            <button
              className="join-item btn btn-sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              «
            </button>
            <button className="join-item btn btn-sm">
              {gettext('Page')} {table.getState().pagination.pageIndex + 1}
            </button>
            <button
              className="join-item btn btn-sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              »
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default LineTable;
