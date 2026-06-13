/* globals gettext */

import React, { useEffect, useState } from 'react';

const DATE_FORMAT_OPTIONS = [
  { value: '%d/%m/%Y', label: 'DD/MM/YYYY', example: '28/02/2025' },
  { value: '%m/%d/%Y', label: 'MM/DD/YYYY', example: '02/28/2025' },
  { value: '%Y-%m-%d', label: 'YYYY-MM-DD', example: '2025-02-28' },
  { value: '%d-%m-%Y', label: 'DD-MM-YYYY', example: '28-02-2025' },
  { value: '%m-%d-%Y', label: 'MM-DD-YYYY', example: '02-28-2025' },
  { value: '%Y/%m/%d', label: 'YYYY/MM/DD', example: '2025/02/28' },
  { value: '%d/%m/%y', label: 'DD/MM/YY', example: '28/02/25' },
  { value: '%m/%d/%y', label: 'MM/DD/YY', example: '02/28/25' },
  { value: '%b %d, %Y', label: 'Mon DD, YYYY', example: 'Feb 28, 2025' },
  { value: '%d %b %Y', label: 'DD Mon YYYY', example: '28 Feb 2025' },
];

/**
 * Detect the most likely date format from a list of sample date strings.
 * Returns a strftime format string or null if no common format is detected.
 */
const detectDateFormat = (sampleValues) => {
  const values = sampleValues.map((v) => (v || '').trim()).filter(Boolean);
  if (!values.length) return null;

  // Year-first patterns (unambiguous)
  if (values.every((v) => /^\d{4}-\d{2}-\d{2}$/.test(v))) return '%Y-%m-%d';
  if (values.every((v) => /^\d{4}\/\d{2}\/\d{2}$/.test(v))) return '%Y/%m/%d';

  // Text month patterns
  if (values.every((v) => /^\w{3,9}\s+\d{1,2},?\s+\d{4}$/.test(v))) return '%b %d, %Y';
  if (values.every((v) => /^\d{1,2}\s+\w{3,9}\s+\d{4}$/.test(v))) return '%d %b %Y';

  // Numeric d/m/y or d-m-y patterns
  const slashRe = /^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/;
  const dashRe = /^(\d{1,2})-(\d{1,2})-(\d{2,4})$/;

  let sep = null;
  const parts = [];
  for (const v of values) {
    const ms = slashRe.exec(v);
    const md = dashRe.exec(v);
    if (ms) {
      if (sep && sep !== '/') return null;
      sep = '/';
      parts.push([+ms[1], +ms[2], ms[3].length]);
    } else if (md) {
      if (sep && sep !== '-') return null;
      sep = '-';
      parts.push([+md[1], +md[2], md[3].length]);
    } else {
      return null;
    }
  }

  if (!parts.length) return null;
  const yearLen = parts[0][2];
  const yearFmt = yearLen === 4 ? '%Y' : '%y';

  // Check which position is unambiguously the day (value > 12)
  const firstExceedsMonth = parts.some(([a]) => a > 12);
  const secondExceedsMonth = parts.some(([, b]) => b > 12);

  if (firstExceedsMonth) {
    return sep === '/' ? `%d/%m/${yearFmt}` : `%d-%m-${yearFmt}`;
  } else if (secondExceedsMonth) {
    return sep === '/' ? `%m/%d/${yearFmt}` : `%m-%d-${yearFmt}`;
  } else {
    // Ambiguous — default to day-first (international convention)
    return sep === '/' ? `%d/%m/${yearFmt}` : `%d-%m-${yearFmt}`;
  }
};

/**
 * Keywords to match for auto-guessing column mappings
 */
const COLUMN_KEYWORDS = {
  date: ['date', 'posted', 'transaction date', 'trans date', 'posting date'],
  description: ['description', 'memo', 'narrative', 'details', 'transaction', 'name'],
  payee: ['payee', 'merchant', 'vendor', 'recipient', 'paid to'],
  category: ['category', 'type', 'classification', 'account', 'expense type'],
  amount: ['amount', 'sum', 'total', 'value', 'transaction amount'],
  inflow: ['inflow', 'credit', 'deposit', 'income', 'money in', 'credits'],
  outflow: ['outflow', 'debit', 'withdrawal', 'expense', 'money out', 'debits', 'payment'],
};

/**
 * Auto-guess column index based on header name
 */
const guessColumnIndex = (headers, field) => {
  const keywords = COLUMN_KEYWORDS[field] || [];

  for (let i = 0; i < headers.length; i++) {
    const header = (headers[i] || '').toLowerCase().trim();
    for (const keyword of keywords) {
      if (header.includes(keyword)) {
        return i;
      }
    }
  }

  return null;
};

/**
 * Auto-guess all column mappings based on headers
 */
const guessAllMappings = (headers) => {
  const mapping = {
    date: guessColumnIndex(headers, 'date'),
    description: guessColumnIndex(headers, 'description'),
    payee: guessColumnIndex(headers, 'payee'),
    category: guessColumnIndex(headers, 'category'),
    amount: guessColumnIndex(headers, 'amount'),
    inflow: guessColumnIndex(headers, 'inflow'),
    outflow: guessColumnIndex(headers, 'outflow'),
  };

  // Determine if dual amount mode should be used
  const hasDualAmount = mapping.inflow !== null || mapping.outflow !== null;

  return { mapping, hasDualAmount };
};

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
  const [hasHeaders, setHasHeaders] = useState(true);
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
  const [dateFormat, setDateFormat] = useState(null);
  const [loading, setLoading] = useState(false);

  // Auto-guess mappings when component mounts or when hasHeaders changes
  useEffect(() => {
    if (hasHeaders && headers.length > 0) {
      const { mapping: guessedMapping, hasDualAmount } = guessAllMappings(headers);
      setMapping(guessedMapping);
      if (hasDualAmount) {
        setAmountType('dual');
      }
    } else {
      // Reset mappings when headers are disabled
      setMapping({
        date: null,
        description: null,
        payee: null,
        category: null,
        amount: null,
        inflow: null,
        outflow: null,
      });
      setAmountType('single');
    }
  }, [headers, hasHeaders]);

  // Auto-detect date format when date column selection changes
  useEffect(() => {
    if (mapping.date !== null && sampleRows.length > 0) {
      const dateSamples = sampleRows.map((row) => row[mapping.date] || '');
      const detected = detectDateFormat(dateSamples);
      setDateFormat(detected);
    } else {
      setDateFormat(null);
    }
  }, [mapping.date, sampleRows]);

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
    await onComplete(mapping, amountType, hasHeaders, dateFormat);
    setLoading(false);
  };

  // Get display headers - use "Column N" if no headers
  const displayHeaders = hasHeaders
    ? headers
    : headers.map((_, index) => `Column ${index + 1}`);

  // Get display sample rows - if no headers, show first row as data
  const displaySampleRows = hasHeaders
    ? sampleRows
    : [headers, ...sampleRows.slice(0, 4)];

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
        {displayHeaders.map((header, index) => (
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

      {/* Has Headers Toggle */}
      <div className="form-control">
        <label className="label cursor-pointer justify-start gap-4">
          <input
            type="checkbox"
            className="checkbox checkbox-primary"
            checked={hasHeaders}
            onChange={(e) => setHasHeaders(e.target.checked)}
          />
          <span className="label-text">{gettext('First row contains column headers')}</span>
        </label>
      </div>

      {/* Column Mapping Form */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {renderColumnSelect('date', gettext('Date'), true)}
        {renderColumnSelect('description', gettext('Description'), true)}
        {renderColumnSelect('payee', gettext('Payee (Optional)'))}
        {renderColumnSelect('category', gettext('Category (Optional)'))}
      </div>

      {/* Date Format Selector */}
      {mapping.date !== null && (
        <div className="form-control">
          <label className="label">
            <span className="label-text font-medium">{gettext('Date Format')}</span>
          </label>
          {dateFormat ? (
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-sm text-base-content/70">
                {gettext('Detected:')}
              </span>
              <select
                className="select select-bordered select-sm"
                value={dateFormat}
                onChange={(e) => setDateFormat(e.target.value)}
              >
                {DATE_FORMAT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label} ({opt.example})
                  </option>
                ))}
                {!DATE_FORMAT_OPTIONS.find((o) => o.value === dateFormat) && (
                  <option value={dateFormat}>{dateFormat}</option>
                )}
              </select>
              <span className="text-xs text-base-content/50">
                {gettext('This format will be applied consistently to every row.')}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-sm text-warning">
                {gettext('Could not detect format automatically. Select one:')}
              </span>
              <select
                className="select select-bordered select-sm"
                value={dateFormat || ''}
                onChange={(e) => setDateFormat(e.target.value || null)}
              >
                <option value="">{gettext('-- Auto-detect per row --')}</option>
                {DATE_FORMAT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label} ({opt.example})
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      )}

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
      {displaySampleRows.length > 0 && (
        <div className="overflow-x-auto">
          <h4 className="font-medium mb-2">{gettext('Data Preview')}</h4>
          <table className="table table-xs table-zebra">
            <thead>
              <tr>
                {displayHeaders.map((header, index) => (
                  <th key={index} className="text-xs">
                    {header || `Col ${index + 1}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displaySampleRows.map((row, rowIndex) => (
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
