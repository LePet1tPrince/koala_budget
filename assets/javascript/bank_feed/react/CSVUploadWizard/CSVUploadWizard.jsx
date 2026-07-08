/* globals gettext */

import React, { useState } from 'react';

import Step1FileUpload from './Step1FileUpload';
import Step2ColumnMapping from './Step2ColumnMapping';
import Step3CategoryMapping from './Step3CategoryMapping';
import Step4DuplicateReview from './Step4DuplicateReview';
import Step5Preview from './Step5Preview';

// Number of transactions sent per upload_confirm request — smaller batches give the
// progress bar more, and more frequent, steps to render for large imports.
const IMPORT_BATCH_SIZE = 25;

/**
 * CSVUploadWizard - Multi-step wizard for uploading bank transactions from CSV/Excel
 *
 * Props:
 * - selectedAccount: The bank account to upload transactions to
 * - allAccounts: All available accounts for category mapping
 * - uploadApi: Upload API helpers (uploadParse, uploadPreview, uploadConfirm)
 * - onComplete: Callback when import is complete
 * - onCancel: Callback when user cancels
 */
const CSVUploadWizard = ({ selectedAccount, allAccounts, allAccountGroups, uploadApi, onComplete, onCancel }) => {
  const [currentStep, setCurrentStep] = useState(1);
  const [error, setError] = useState(null);

  // Step 1 state
  const [file, setFile] = useState(null);
  const [parseResult, setParseResult] = useState(null);

  // Step 2 state
  const [columnMapping, setColumnMapping] = useState({
    date: null,
    description: null,
    payee: null,
    category: null,
    amount: null,
    inflow: null,
    outflow: null,
  });
  const [amountType, setAmountType] = useState('single'); // 'single' or 'dual'
  const [hasHeaders, setHasHeaders] = useState(true);

  // Step 2 extra state
  const [dateFormat, setDateFormat] = useState(null);

  // Step 3 state
  const [categoryMappings, setCategoryMappings] = useState({});
  // Original unmapped categories from the first preview — preserved so Step 3 always shows
  // the full list even after mappings are applied and previewResult.unmapped_categories empties out.
  const [originalUnmappedCategories, setOriginalUnmappedCategories] = useState(null);

  // Step 4 (duplicate review) state — row_numbers the user chose to exclude
  const [excludedDuplicateRows, setExcludedDuplicateRows] = useState(new Set());

  // Step 5 state
  const [previewResult, setPreviewResult] = useState(null);
  const [importProgress, setImportProgress] = useState(null); // { completed, total }

  // Derived helpers — step 3 is always shown once we have a preview result
  const showStep3 = originalUnmappedCategories !== null;
  const showStep4 = previewResult?.duplicate_count > 0;

  /**
   * Handle file upload and parsing (Step 1)
   */
  const handleFileUpload = async (uploadedFile) => {
    setFile(uploadedFile);
    setError(null);

    try {
      const result = await uploadApi.uploadParse(uploadedFile);

      if (result.error) {
        throw new Error(result.error);
      }

      setParseResult(result);
      setCurrentStep(2);
    } catch (err) {
      console.error('File upload error:', err);
      setError(err.message || gettext('Failed to upload file'));
    }
  };

  /**
   * Handle column mapping (Step 2)
   */
  const handleColumnMappingComplete = async (mapping, amtType, fileHasHeaders, detectedDateFormat) => {
    setColumnMapping(mapping);
    setAmountType(amtType);
    setHasHeaders(fileHasHeaders);
    setDateFormat(detectedDateFormat);
    setError(null);

    try {
      const result = await uploadApi.uploadPreview(
        file,
        selectedAccount.id,
        { ...mapping, has_headers: fileHasHeaders },
        [],
        detectedDateFormat
      );

      setPreviewResult(result);
      setExcludedDuplicateRows(new Set());
      // Freeze the original list so Step 3 can always show it, even after mappings are applied
      setOriginalUnmappedCategories(result.unmapped_categories || []);
      // Always visit step 3 so the user can review/map categories
      setCurrentStep(3);
    } catch (err) {
      console.error('Preview error:', err);
      setError(err.message || gettext('Failed to preview transactions'));
    }
  };

  /**
   * Handle category mapping (Step 3)
   */
  const handleCategoryMappingComplete = async (mappings) => {
    setCategoryMappings(mappings);
    setError(null);

    try {
      const categoryMappingsList = Object.entries(mappings).map(([name, accountId]) => ({
        category_name: name,
        account_id: accountId,
      }));

      const result = await uploadApi.uploadPreview(
        file,
        selectedAccount.id,
        { ...columnMapping, has_headers: hasHeaders },
        categoryMappingsList,
        dateFormat
      );

      setPreviewResult(result);
      setExcludedDuplicateRows(new Set());

      if (result.duplicate_count > 0) {
        setCurrentStep(4);
      } else {
        setCurrentStep(5);
      }
    } catch (err) {
      console.error('Preview error:', err);
      setError(err.message || gettext('Failed to preview transactions'));
    }
  };

  /**
   * Handle duplicate review (Step 4)
   */
  const handleDuplicateReviewContinue = () => {
    setCurrentStep(5);
  };

  /**
   * Handle import confirmation (Step 5)
   */
  const handleConfirm = async (transactionsToImport) => {
    setError(null);
    setImportProgress({ completed: 0, total: transactionsToImport.length });

    // Send in batches (rather than one request) so we can report incremental progress
    const batches = [];
    for (let i = 0; i < transactionsToImport.length; i += IMPORT_BATCH_SIZE) {
      batches.push(transactionsToImport.slice(i, i + IMPORT_BATCH_SIZE));
    }

    const aggregateResult = { created_count: 0, skipped_count: 0, error_count: 0 };

    try {
      for (const batch of batches) {
        // skip_duplicates=false because the user already decided per-row in step 4
        const result = await uploadApi.uploadConfirm(selectedAccount.id, batch, false);

        aggregateResult.created_count += result.created_count || 0;
        aggregateResult.skipped_count += result.skipped_count || 0;
        aggregateResult.error_count += result.error_count || 0;

        setImportProgress((prev) => ({ ...prev, completed: prev.completed + batch.length }));
      }

      onComplete(aggregateResult);
    } catch (err) {
      console.error('Import error:', err);
      setError(err.message || gettext('Failed to import transactions'));
    } finally {
      setImportProgress(null);
    }
  };

  /**
   * Go back to previous step
   */
  const handleBack = () => {
    if (currentStep === 5) {
      if (showStep4) {
        setCurrentStep(4);
      } else if (showStep3) {
        setCurrentStep(3);
      } else {
        setCurrentStep(2);
      }
    } else if (currentStep === 4) {
      if (showStep3) {
        setCurrentStep(3);
      } else {
        setCurrentStep(2);
      }
    } else if (currentStep > 1) {
      setCurrentStep(currentStep - 1);
    }
  };

  // Build visible steps for the indicator
  const steps = [
    { number: 1, label: gettext('Upload') },
    { number: 2, label: gettext('Map Columns') },
    ...(showStep3 ? [{ number: 3, label: gettext('Map Categories') }] : []),
    ...(showStep4 ? [{ number: 4, label: gettext('Review Duplicates') }] : []),
    { number: 5, label: gettext('Preview') },
  ];

  // Map step numbers to display position for the indicator
  const stepPosition = (stepNumber) => steps.findIndex((s) => s.number === stepNumber) + 1;
  const currentPosition = stepPosition(currentStep);
  const totalPositions = steps.length;

  return (
    <div className="modal modal-open">
      <div className="modal-box max-w-5xl">
        <h3 className="font-bold text-lg mb-2">
          {gettext('Upload Transactions to')} {selectedAccount.name}
        </h3>

        {/* Step Indicator */}
        <ul className="steps steps-horizontal w-full mb-6">
          {steps.map((step, idx) => (
            <li
              key={step.number}
              className={`step ${currentPosition >= idx + 1 ? 'step-primary' : ''}`}
            >
              {step.label}
            </li>
          ))}
        </ul>

        {error && (
          <div className="alert alert-error mb-4">
            <i className="fa fa-exclamation-circle"></i>
            <span>{error}</span>
          </div>
        )}

        {/* Step Content */}
        {currentStep === 1 && (
          <Step1FileUpload
            onFileUpload={handleFileUpload}
            onCancel={onCancel}
          />
        )}

        {currentStep === 2 && parseResult && (
          <Step2ColumnMapping
            headers={parseResult.headers}
            sampleRows={parseResult.sample_rows}
            totalRows={parseResult.total_rows}
            onComplete={handleColumnMappingComplete}
            onBack={handleBack}
            onCancel={onCancel}
          />
        )}

        {currentStep === 3 && originalUnmappedCategories !== null && (
          <Step3CategoryMapping
            unmappedCategories={originalUnmappedCategories}
            initialMappings={categoryMappings}
            allAccounts={allAccounts}
            allAccountGroups={allAccountGroups}
            uploadApi={uploadApi}
            onComplete={handleCategoryMappingComplete}
            onBack={handleBack}
            onCancel={onCancel}
          />
        )}

        {currentStep === 4 && previewResult && (
          <Step4DuplicateReview
            duplicates={previewResult.transactions.filter((tx) => tx.is_potential_duplicate)}
            excludedRows={excludedDuplicateRows}
            onExcludedRowsChange={setExcludedDuplicateRows}
            onContinue={handleDuplicateReviewContinue}
            onBack={handleBack}
            onCancel={onCancel}
          />
        )}

        {currentStep === 5 && previewResult && (
          <Step5Preview
            transactions={previewResult.transactions}
            errorCount={previewResult.error_count}
            excludedDuplicateRows={excludedDuplicateRows}
            importProgress={importProgress}
            onConfirm={handleConfirm}
            onBack={handleBack}
            onCancel={onCancel}
          />
        )}
      </div>
    </div>
  );
};

export default CSVUploadWizard;
