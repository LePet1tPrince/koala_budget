/* globals gettext */

import React, { useState } from 'react';

import { Toast } from '../common/Toast';
import Step1Export from './Step1Export';
import Step2Upload from './Step2Upload';
import Step3Confirm from './Step3Confirm';
import Step4Apply from './Step4Apply';

/**
 * Four screens over one piece of state: `screen`. There is no wizard *choice*
 * to carry between them the way the YNAB importer carries inferred answers --
 * both ends of this feature are Koala Budget, so nothing needs inferring
 * (docs/export-import-plan.md §1) -- just the upload's response, carried
 * forward so Confirm can show it and Apply knows which import to poll.
 *
 * `resume` is deliberately narrow: only a *running* import is picked back up
 * on page load. An uploaded-but-unconfirmed one has no cached comparison
 * data to show on Confirm (nothing persists it), so reloading mid-upload
 * just starts over -- harmless, since nothing has been written yet either way.
 */
const DataTransferWizard = ({ props }) => {
  const { api, urls, bookName, uncategorizedCount, bankFeedUrl, homeUrl, resume } = props;

  const [screen, setScreen] = useState(resume?.status === 'running' ? 'apply' : 'export');
  const [uploadResult, setUploadResult] = useState(null);
  const [importId, setImportId] = useState(resume?.id ?? null);
  const [toast, setToast] = useState(null);

  const showError = (error) => setToast({ message: error.message || String(error), severity: 'error' });

  const handleUploaded = (payload) => {
    setImportId(payload.import_id);
    setUploadResult(payload);
    setScreen('confirm');
  };

  const handleApplyStarted = (id) => {
    setImportId(id);
    setScreen('apply');
  };

  const startOver = () => {
    setUploadResult(null);
    setImportId(null);
    setScreen('upload');
  };

  return (
    <div className="space-y-6">
      {screen === 'export' && (
        <Step1Export
          exportUrl={urls.export}
          uncategorizedCount={uncategorizedCount}
          bankFeedUrl={bankFeedUrl}
          onStartImport={() => setScreen('upload')}
        />
      )}

      {screen === 'upload' && (
        <Step2Upload api={api} onUploaded={handleUploaded} onError={showError} onCancel={() => setScreen('export')} />
      )}

      {screen === 'confirm' && uploadResult && (
        <Step3Confirm
          api={api}
          importId={importId}
          bookName={bookName}
          file={uploadResult.file}
          destination={uploadResult.destination}
          onApplyStarted={handleApplyStarted}
          onError={showError}
          onCancel={startOver}
        />
      )}

      {screen === 'apply' && importId && (
        <Step4Apply
          api={api}
          importId={importId}
          safetyExportUrl={urls.safetyExport}
          homeUrl={homeUrl}
          onStartOver={startOver}
        />
      )}

      <Toast
        open={Boolean(toast)}
        message={toast?.message}
        severity={toast?.severity}
        onClose={() => setToast(null)}
      />
    </div>
  );
};

export default DataTransferWizard;
