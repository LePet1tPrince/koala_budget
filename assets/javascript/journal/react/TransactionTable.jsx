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
 * TransactionTable component - displays and edits transactions using TanStack Table
 */
const TransactionTable = ({
  transactions,
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
  const [newTransaction, setNewTransaction] = useState({
    date: new Date().toISOString().split('T')[0],
    account: selectedAccount?.account_id || '',
    category: '',
    amount: '',
    description: '',
    payee: '',
  });

  // Format currency
  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(amount);
  };

  // Format date
  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleDateString();
  };

  // Get account name by ID
  const getAccountName = (accountId) => {
    const account = allAccounts.find((a) => a.account_id === accountId);
    return account ? account.name : '';
  };

  // Get payee name by ID
  const getPayeeName = (payeeId) => {
    if (!payeeId) return '';
    const payee = allPayees.find((p) => p.payee_id === payeeId);
    return payee ? payee.name : '';
  };

  // Handle edit start
  const handleEditStart = (row) => {
    setEditingRow(row.id);
    setEditData({
      date: row.original.date,
      account: row.original.account,
      category: row.original.category,
      amount: row.original.amount,
      description: row.original.description,
      payee: row.original.payee || '',
    });
  };

  // Handle edit save
  const handleEditSave = async (row) => {
    try {
      await onUpdate(row.original.id, editData);
      setEditingRow(null);
      setEditData({});
    } catch (error) {
      console.error('Failed to update transaction:', error);
      alert(gettext('Failed to update transaction'));
    }
  };

  // Handle edit cancel
  const handleEditCancel = () => {
    setEditingRow(null);
    setEditData({});
  };

  // Handle add transaction
  const handleAddTransaction = async () => {
    console.log('=== TransactionTable handleAddTransaction called ===');
    console.log('New transaction data:', newTransaction);
    console.log('Selected account:', selectedAccount);

    // Validate the data before sending
    console.log('Validating transaction data...');
    if (!newTransaction.date) {
      console.error('Validation failed: date is required');
      alert(gettext('Date is required'));
      return;
    }
    if (!newTransaction.account) {
      console.error('Validation failed: account is required');
      alert(gettext('Account is required'));
      return;
    }
    if (!newTransaction.category) {
      console.error('Validation failed: category is required');
      alert(gettext('Category is required'));
      return;
    }
    if (!newTransaction.amount) {
      console.error('Validation failed: amount is required');
      alert(gettext('Amount is required'));
      return;
    }

    console.log('Validation passed, calling onAdd...');

    try {
      await onAdd(newTransaction);
      console.log('Transaction added successfully');
      setIsAdding(false);
      setNewTransaction({
        date: new Date().toISOString().split('T')[0],
        account: selectedAccount?.account_id || '',
        category: '',
        amount: '',
        description: '',
        payee: '',
      });
    } catch (error) {
      console.error('=== ERROR in TransactionTable handleAddTransaction ===');
      console.error('Error:', error);
      alert(gettext('Failed to add transaction'));
    }
  };

  // Handle delete
  const handleDelete = async (row) => {
    if (confirm(gettext('Are you sure you want to delete this transaction?'))) {
      try {
        await onDelete(row.original.id);
      } catch (error) {
        console.error('Failed to delete transaction:', error);
        alert(gettext('Failed to delete transaction'));
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
        accessorKey: 'categoryName',
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
          return getValue();
        },
      },
      {
        accessorKey: 'amount',
        header: gettext('Amount'),
        cell: ({ row, getValue }) => {
          if (editingRow === row.id) {
            return (
              <input
                type="number"
                step="0.01"
                className="input input-sm input-bordered w-full"
                value={editData.amount}
                onChange={(e) => setEditData({ ...editData, amount: e.target.value })}
              />
            );
          }
          return formatCurrency(getValue());
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
                  <option key={payee.payee_id} value={payee.payee_id}>
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
    data: transactions,
    columns,
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
        <span>{gettext('Please select an account to view transactions')}</span>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Add Transaction Button */}
      {!isAdding && (
        <button
          className="btn btn-primary"
          onClick={() => setIsAdding(true)}
        >
          <i className="fa fa-plus"></i>
          {gettext('Add Transaction')}
        </button>
      )}

      {/* Add Transaction Form */}
      {isAdding && (
        <div className="card bg-base-200 shadow-md">
          <div className="card-body">
            <h3 className="card-title">{gettext('New Transaction')}</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              <div className="form-control">
                <label className="label">
                  <span className="label-text">{gettext('Date')}</span>
                </label>
                <input
                  type="date"
                  className="input input-bordered"
                  value={newTransaction.date}
                  onChange={(e) => setNewTransaction({ ...newTransaction, date: e.target.value })}
                />
              </div>
              <div className="form-control">
                <label className="label">
                  <span className="label-text">{gettext('Category')}</span>
                </label>
                <select
                  className="select select-bordered"
                  value={newTransaction.category}
                  onChange={(e) => setNewTransaction({ ...newTransaction, category: parseInt(e.target.value) })}
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
                  <span className="label-text">{gettext('Amount')}</span>
                </label>
                <input
                  type="number"
                  step="0.01"
                  className="input input-bordered"
                  value={newTransaction.amount}
                  onChange={(e) => setNewTransaction({ ...newTransaction, amount: e.target.value })}
                />
              </div>
              <div className="form-control md:col-span-2">
                <label className="label">
                  <span className="label-text">{gettext('Description')}</span>
                </label>
                <input
                  type="text"
                  className="input input-bordered"
                  value={newTransaction.description}
                  onChange={(e) => setNewTransaction({ ...newTransaction, description: e.target.value })}
                />
              </div>
              <div className="form-control">
                <label className="label">
                  <span className="label-text">{gettext('Payee')}</span>
                </label>
                <select
                  className="select select-bordered"
                  value={newTransaction.payee}
                  onChange={(e) => setNewTransaction({ ...newTransaction, payee: e.target.value ? parseInt(e.target.value) : null })}
                >
                  <option value="">{gettext('None')}</option>
                  {allPayees.map((payee) => (
                    <option key={payee.payee_id} value={payee.payee_id}>
                      {payee.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="card-actions justify-end mt-4">
              <button className="btn btn-ghost" onClick={() => setIsAdding(false)}>
                {gettext('Cancel')}
              </button>
              <button className="btn btn-primary" onClick={handleAddTransaction}>
                {gettext('Save')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Transactions Table */}
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
                  {gettext('No transactions found')}
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

export default TransactionTable;
