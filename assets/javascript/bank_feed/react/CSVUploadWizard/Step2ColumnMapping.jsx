/* globals gettext */

import React, { useState } from 'react';

/**
 * Step2ColumnMapping - Map file columns to transaction fields
 *
 * Props:
 * - headers: Array of column headers from the file
 * - sampleRows: Sample data rows for preview
 * - totalRows: Total number of rows in the file
 * - onComplete: Callback with column mapping
 * - onBack: Callback to go back
 * - onCancel: Callback when user cancels
 */
const Step2ColumnMapping = ({ headers, sampleRows, totalRows, onComplete, onBack, onCancel }) => {
  const [mapping, setMapping] = useState({
    date: null,
    description: null,
    payee: null,
    category: null,
    amount: null,
    inflow: null,
    outflow: null,
  });
  const [amountType, setAmountType] = useState('single'); // 'single' or 'dual'
  const [loading, setLoading] = useState(false);

  const handleMappingChange = (field, columnIndex) => {
    const value = columnIndex === '' ? null : parseInt(columnIndex, 10);
    setMapping((prev) => ({
      ...prev,
      [field]: value,
    }));
  };

  const handleAmountTypeChange = (type) => {
    setAmountType(type);
    // Clear amount-related mappings when switching type
    if (type === 'single') {
      setMapping((prev) => ({
        ...prev,
        inflow: null,
        outflow: null,
      }));
    } else {
      setMapping((prev) => ({
        ...prev,
        amount: null,
      }));
    }
  };

  const isValid = () => {
    // Date and description are required
    if (mapping.date === null || mapping.description === null) {
      return false;
    }

    // Either single amount or at least one of inflow/outflow is required
    if (amountType === 'single') {
      return mapping.amount !== null;
    } else {
      return mapping.inflow !== null || mapping.outflow !== null;
    }
  };

  const handleComplete = async () => {
    if (!isValid()) return;

    setLoading(true);
    await onComplete(mapping, amountType);
    setLoading(false);
  };

  const renderColumnSelect = (field, label, required = false) => (
    <div className="form-control">
      <label className="label">
        <span className="label-text">
          {label}
          {required && <span className="text-error ml-1">*</span>}
        </span>
      </label>
      <select
        className="select select-bordered w-full"
        value={mapping[field] ?? ''}
        onChange={(e) => handleMappingChange(field, e.target.value)}
      >
        <option value="">{gettext('-- Select column --')}</option>
        {headers.map((header, index) => (
          <option key={index} value={index}>
            {header || `Column ${index + 1}`}
          </option>
        ))}
      </select>
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="text-sm text-base-content/70">
        {gettext('Found')} {totalRows} {gettext('rows in file. Map the columns to transaction fields below.')}
      </div>

      {/* Column Mapping Form */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {renderColumnSelect('date', gettext('Date'), true)}
        {renderColumnSelect('description', gettext('Description'), true)}
        {renderColumnSelect('payee', gettext('Payee (Optional)'))}
        {renderColumnSelect('category', gettext('Category (Optional)'))}
      </div>

      {/* Amount Type Toggle */}
      <div className="form-control">
        <label className="label">
          <span className="label-text font-medium">{gettext('Amount Format')}</span>
        </label>
        <div className="flex gap-4">
          <label className="label cursor-pointer gap-2">
            <input
              type="radio"
              name="amount-type"
              className="radio radio-primary"
              checked={amountType === 'single'}
              onChange={() => handleAmountTypeChange('single')}
            />
            <span className="label-text">{gettext('Single column (+/-)')}</span>
          </label>
          <label className="label cursor-pointer gap-2">
            <input
              type="radio"
              name="amount-type"
              className="radio radio-primary"
              checked={amountType === 'dual'}
              onChange={() => handleAmountTypeChange('dual')}
            />
            <span className="label-text">{gettext('Separate inflow/outflow')}</span>
          </label>
        </div>
      </div>

      {/* Amount Column(s) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {amountType === 'single' ? (
          renderColumnSelect('amount', gettext('Amount'), true)
        ) : (
          <>
            {renderColumnSelect('inflow', gettext('Inflow (Money In)'))}
            {renderColumnSelect('outflow', gettext('Outflow (Money Out)'))}
          </>
        )}
      </div>

      {/* Sample Data Preview */}
      {sampleRows.length > 0 && (
        <div className="overflow-x-auto">
          <h4 className="font-medium mb-2">{gettext('Data Preview')}</h4>
          <table className="table table-xs table-zebra">
            <thead>
              <tr>
                {headers.map((header, index) => (
                  <th key={index} className="text-xs">
                    {header || `Col ${index + 1}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sampleRows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex} className="text-xs max-w-32 truncate">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="modal-action">
        <button
          className="btn btn-ghost"
          onClick={onCancel}
          disabled={loading}
        >
          {gettext('Cancel')}
        </button>
        <button
          className="btn btn-ghost"
          onClick={onBack}
          disabled={loading}
        >
          {gettext('Back')}
        </button>
        <button
          className="btn btn-primary"
          onClick={handleComplete}
          disabled={!isValid() || loading}
        >
          {loading ? (
            <>
              <span className="loading loading-spinner loading-sm"></span>
              {gettext('Processing...')}
            </>
          ) : (
            gettext('Next')
          )}
        </button>
      </div>
    </div>
  );
};

export default Step2ColumnMapping;
