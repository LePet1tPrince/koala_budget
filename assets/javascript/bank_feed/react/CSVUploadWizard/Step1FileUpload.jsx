/* globals gettext */

import React, { useCallback, useState } from 'react';

/**
 * Step1FileUpload - File upload step with drag-drop support
 *
 * Props:
 * - onFileUpload: Callback when file is selected
 * - onCancel: Callback when user cancels
 */
const Step1FileUpload = ({ onFileUpload, onCancel }) => {
  const [isDragging, setIsDragging] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleDragEnter = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      handleFile(files[0]);
    }
  }, []);

  const handleFileInput = useCallback((e) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFile(files[0]);
    }
  }, []);

  const handleFile = async (file) => {
    // Validate file type
    const validTypes = [
      'text/csv',
      'application/vnd.ms-excel',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    ];
    const validExtensions = ['.csv', '.xls', '.xlsx'];
    const fileExtension = file.name.toLowerCase().substring(file.name.lastIndexOf('.'));

    if (!validTypes.includes(file.type) && !validExtensions.includes(fileExtension)) {
      alert(gettext('Please upload a CSV or Excel file (.csv, .xls, .xlsx)'));
      return;
    }

    setLoading(true);
    await onFileUpload(file);
    setLoading(false);
  };

  return (
    <div className="space-y-6">
      <div
        className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${
          isDragging
            ? 'border-primary bg-primary/10'
            : 'border-base-300 hover:border-primary/50'
        }`}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        {loading ? (
          <div className="flex flex-col items-center">
            <span className="loading loading-spinner loading-lg mb-4"></span>
            <p className="text-base-content/70">{gettext('Parsing file...')}</p>
          </div>
        ) : (
          <>
            <i className="fa fa-cloud-upload text-5xl text-base-content/50 mb-4"></i>
            <p className="text-lg mb-2">
              {gettext('Drag and drop your file here')}
            </p>
            <p className="text-sm text-base-content/70 mb-4">
              {gettext('or')}
            </p>
            <label className="btn btn-primary">
              <i className="fa fa-folder-open mr-2"></i>
              {gettext('Browse Files')}
              <input
                type="file"
                className="hidden"
                accept=".csv,.xls,.xlsx"
                onChange={handleFileInput}
                data-testid="csv-file-input"
              />
            </label>
            <p className="text-xs text-base-content/50 mt-4">
              {gettext('Supported formats: CSV, Excel (.xls, .xlsx)')}
            </p>
          </>
        )}
      </div>

      <div className="modal-action">
        <button
          className="btn btn-ghost"
          onClick={onCancel}
          disabled={loading}
          data-testid="csv-upload-cancel-btn"
        >
          {gettext('Cancel')}
        </button>
      </div>
    </div>
  );
};

export default Step1FileUpload;
