/* globals gettext */

import React, { useState } from 'react';

import Step1FileUpload from './Step1FileUpload';
import Step2ColumnMapping from './Step2ColumnMapping';
import Step3CategoryMapping from './Step3CategoryMapping';
import Step4Preview from './Step4Preview';

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
const CSVUploadWizard = ({ selectedAccount, allAccounts, uploadApi, onComplete, onCancel }) => {
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

  // Step 3 state
  const [categoryMappings, setCategoryMappings] = useState({});

  // Step 4 state
  const [previewResult, setPreviewResult] = useState(null);
  const [skipDuplicates, setSkipDuplicates] = useState(true);

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
  const handleColumnMappingComplete = async (mapping, amtType, fileHasHeaders) => {
    setColumnMapping(mapping);
    setAmountType(amtType);
    setHasHeaders(fileHasHeaders);
    setError(null);

    try {
      const result = await uploadApi.uploadPreview(
        file,
        selectedAccount.id,
        { ...mapping, has_headers: fileHasHeaders },
        []
      );

      setPreviewResult(result);

      // If there are unmapped categories, go to step 3, otherwise skip to step 4
      if (result.unmapped_categories && result.unmapped_categories.length > 0) {
        setCurrentStep(3);
      } else {
        setCurrentStep(4);
      }
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
      // Re-run preview with category mappings
      const categoryMappingsList = Object.entries(mappings).map(([name, accountId]) => ({
        category_name: name,
        account_id: accountId,
      }));

      const result = await uploadApi.uploadPreview(
        file,
        selectedAccount.id,
        { ...columnMapping, has_headers: hasHeaders },
        categoryMappingsList
      );

      setPreviewResult(result);
      setCurrentStep(4);
    } catch (err) {
      console.error('Preview error:', err);
      setError(err.message || gettext('Failed to preview transactions'));
    }
  };

  /**
   * Handle import confirmation (Step 4)
   */
  const handleConfirm = async (transactionsToImport) => {
    setError(null);

    try {
      const result = await uploadApi.uploadConfirm(
        selectedAccount.id,
        transactionsToImport,
        skipDuplicates
      );

      onComplete(result);
    } catch (err) {
      console.error('Import error:', err);
      setError(err.message || gettext('Failed to import transactions'));
    }
  };

  /**
   * Go back to previous step
   */
  const handleBack = () => {
    if (currentStep === 4 && previewResult?.unmapped_categories?.length > 0) {
      setCurrentStep(3);
    } else if (currentStep > 1) {
      setCurrentStep(currentStep - 1);
    }
  };

  const steps = [
    { number: 1, label: gettext('Upload') },
    { number: 2, label: gettext('Map Columns') },
    { number: 3, label: gettext('Map Categories') },
    { number: 4, label: gettext('Preview') },
  ];

  // Determine if step 3 should be shown
  const showStep3 = previewResult?.unmapped_categories?.length > 0;

  return (
    <div className="modal modal-open">
      <div className="modal-box max-w-4xl">
        <h3 className="font-bold text-lg mb-2">
          {gettext('Upload Transactions to')} {selectedAccount.name}
        </h3>

        {/* Step Indicator */}
        <ul className="steps steps-horizontal w-full mb-6">
          {steps.map((step) => {
            // Skip step 3 if no categories to map and we're past step 2
            if (step.number === 3 && !showStep3 && currentStep > 2) {
              return null;
            }
            return (
              <li
                key={step.number}
                className={`step ${currentStep >= step.number ? 'step-primary' : ''}`}
              >
                {step.label}
              </li>
            );
          })}
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

        {currentStep === 3 && previewResult && (
          <Step3CategoryMapping
            unmappedCategories={previewResult.unmapped_categories}
            allAccounts={allAccounts}
            onComplete={handleCategoryMappingComplete}
            onBack={handleBack}
            onCancel={onCancel}
          />
        )}

        {currentStep === 4 && previewResult && (
          <Step4Preview
            transactions={previewResult.transactions}
            errorCount={previewResult.error_count}
            duplicateCount={previewResult.duplicate_count}
            skipDuplicates={skipDuplicates}
            onSkipDuplicatesChange={setSkipDuplicates}
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
