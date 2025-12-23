/* globals gettext */
import React, { useMemo, useState } from 'react';
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table';

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
  const [editData, setEditData] = useState({});
  const [isAdding, setIsAdding] = useState(false);
  const [newLine, setNewLine] = useState({
    date: new Date().toISOString().split('T')[0],
    account: selectedAccount?.account_id || '',
    category: '',
    inflow: '',
    outflow: '',
    description: '',
    payee: '',
    is_cleared: false,
    is_reconciled: false,
  });

  // Format currency
  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(amount);
  };

  // Format date for display
  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleDateString();
  };

  // Format date for input field (YYYY-MM-DD)
  const formatDateForInput = (dateString) => {
    if (!dateString) return '';
    const date = new Date(dateString);
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
    setEditData({
      date: formatDateForInput(row.original.date),
      account: row.original.account,
      category: row.original.category,
      inflow: row.original.inflow,
      outflow: row.original.outflow,
      description: row.original.description,
      payee: row.original.payee || '',
      is_cleared: row.original.is_cleared,
      is_reconciled: row.original.is_reconciled,
    });
  };

  // Handle edit save
  const handleEditSave = async (row) => {
    try {
      await onUpdate(row.original.line_id, editData);
      setEditingRow(null);
      setEditData({});
    } catch (error) {
      console.error('Failed to update line:', error);
      alert(gettext('Failed to update line'));
    }
  };

  // Handle edit cancel
  const handleEditCancel = () => {
    setEditingRow(null);
    setEditData({});
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
        is_cleared: false,
        is_reconciled: false,
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
        await onDelete(row.original.line_id);
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
        cell: ({ row, getValue }) => {
          if (editingRow === row.id) {
            return (
              <input
                type="date"
                className="input input-sm input-bordered w-full"
                value={editData.date}
                onChange={(e) => setEditData({ ...editData, date: e.target.value })}
              />
            );
          }
          return formatDate(getValue());
        },
      },
      {
        accessorKey: 'category',
        header: gettext('Category'),
        cell: ({ row, getValue }) => {
          if (editingRow === row.id) {
            return (
              <select
                className="select select-sm select-bordered w-full"
                value={editData.category}
                onChange={(e) => setEditData({ ...editData, category: parseInt(e.target.value) })}
              >
                <option value="">{gettext('Select category')}</option>
                {allAccounts.map((account) => (
                  <option key={account.account_id} value={account.account_id}>
                    {account.account_number} - {account.name}
                  </option>
                ))}
              </select>
            );
          }
          const categoryId = getValue();
          const account = allAccounts.find((a) => a.account_id === categoryId);
          return account ? `${account.account_number} - ${account.name}` : '';
        },
      },
      {
        accessorKey: 'inflow',
        header: gettext('Inflow'),
        cell: ({ row, getValue }) => {
          if (editingRow === row.id) {
            return (
              <input
                type="number"
                step="0.01"
                className="input input-sm input-bordered w-full"
                value={editData.inflow}
                onChange={(e) => {
                  const newValue = e.target.value;
                  setEditData({ ...editData, inflow: newValue });
                }}
                onBlur={(e) => {
                  const newValue = e.target.value;
                  // Clear outflow if inflow has a value
                  if (newValue && parseFloat(newValue) > 0) {
                    setEditData({ ...editData, inflow: newValue, outflow: '0' });
                  }
                }}
              />
            );
          }
          const value = getValue();
          return value && parseFloat(value) > 0 ? formatCurrency(value) : '';
        },
      },
      {
        accessorKey: 'outflow',
        header: gettext('Outflow'),
        cell: ({ row, getValue }) => {
          if (editingRow === row.id) {
            return (
              <input
                type="number"
                step="0.01"
                className="input input-sm input-bordered w-full"
                value={editData.outflow}
                onChange={(e) => {
                  const newValue = e.target.value;
                  setEditData({ ...editData, outflow: newValue });
                }}
                onBlur={(e) => {
                  const newValue = e.target.value;
                  // Clear inflow if outflow has a value
                  if (newValue && parseFloat(newValue) > 0) {
                    setEditData({ ...editData, outflow: newValue, inflow: '0' });
                  }
                }}
              />
            );
          }
          const value = getValue();
          return value && parseFloat(value) > 0 ? formatCurrency(value) : '';
        },
      },
      {
        accessorKey: 'description',
        header: gettext('Description'),
        cell: ({ row, getValue }) => {
          if (editingRow === row.id) {
            return (
              <input
                type="text"
                className="input input-sm input-bordered w-full"
                value={editData.description}
                onChange={(e) => setEditData({ ...editData, description: e.target.value })}
              />
            );
          }
          return getValue();
        },
      },
      {
        accessorKey: 'payee',
        header: gettext('Payee'),
        cell: ({ row, getValue }) => {
          if (editingRow === row.id) {
            return (
              <select
                className="select select-sm select-bordered w-full"
                value={editData.payee}
                onChange={(e) => setEditData({ ...editData, payee: e.target.value ? parseInt(e.target.value) : null })}
              >
                <option value="">{gettext('None')}</option>
                {allPayees.map((payee) => (
                  <option key={payee.id} value={payee.id}>
                    {payee.name}
                  </option>
                ))}
              </select>
            );
          }
          return getPayeeName(getValue());
        },
      },
      {
        accessorKey: 'is_cleared',
        header: gettext('Cleared'),
        cell: ({ row, getValue }) => {
          if (editingRow === row.id) {
            return (
              <input
                type="checkbox"
                className="checkbox checkbox-sm"
                checked={editData.is_cleared}
                onChange={(e) => setEditData({ ...editData, is_cleared: e.target.checked })}
              />
            );
          }
          return getValue() ? <i className="fa fa-check text-success"></i> : '';
        },
      },
      {
        accessorKey: 'is_reconciled',
        header: gettext('Reconciled'),
        cell: ({ row, getValue }) => {
          if (editingRow === row.id) {
            return (
              <input
                type="checkbox"
                className="checkbox checkbox-sm"
                checked={editData.is_reconciled}
                onChange={(e) => setEditData({ ...editData, is_reconciled: e.target.checked })}
              />
            );
          }
          return getValue() ? <i className="fa fa-check text-success"></i> : '';
        },
      },
      {
        id: 'actions',
        header: gettext('Actions'),
        cell: ({ row }) => {
          if (editingRow === row.id) {
            return (
              <div className="flex gap-1">
                <button
                  className="btn btn-sm btn-success"
                  onClick={() => handleEditSave(row)}
                >
                  <i className="fa fa-check"></i>
                </button>
                <button
                  className="btn btn-sm btn-ghost"
                  onClick={handleEditCancel}
                >
                  <i className="fa fa-times"></i>
                </button>
              </div>
            );
          }
          return (
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
          );
        },
      },
    ],
    [editingRow, editData, allAccounts, allPayees]
  );

  // Create table instance
  const table = useReactTable({
    data: lines,
    columns,
    getRowId: (row) => row.line_id,
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
                    checked={newLine.is_cleared}
                    onChange={(e) => setNewLine({ ...newLine, is_cleared: e.target.checked })}
                  />
                </label>
              </div>
              <div className="form-control">
                <label className="label cursor-pointer">
                  <span className="label-text">{gettext('Reconciled')}</span>
                  <input
                    type="checkbox"
                    className="checkbox"
                    checked={newLine.is_reconciled}
                    onChange={(e) => setNewLine({ ...newLine, is_reconciled: e.target.checked })}
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
              table.getRowModel().rows.map((row) => (
                <tr key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  ))}
                </tr>
              ))
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
