/* globals gettext */

import React, { useRef, useState } from 'react';

import Icon from '../common/Icon';
import Spinner from '../common/Spinner';

const Step2Upload = ({ api, onUploaded, onError, onCancel }) => {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [fileName, setFileName] = useState('');

  const handleFile = async (file) => {
    if (!file) return;
    setFileName(file.name);
    setBusy(true);
    try {
      const payload = await api.upload(file);
      onUploaded(payload);
    } catch (error) {
      onError(error);
      setBusy(false);
    }
  };

  return (
    <div className="app-card space-y-4" data-testid="upload-step">
      <div>
        <h2 className="text-lg font-semibold">{gettext('Import into this team')}</h2>
        <p className="text-base-content/70 text-sm mt-1">
          {gettext('Choose the .zip a Koala Budget export produced. Nothing changes yet — the next screen shows exactly what would happen before anything is written.')}
        </p>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".zip"
        className="hidden"
        data-testid="upload-input"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />

      <button
        type="button"
        className="btn btn-outline w-full border-dashed h-28 flex-col gap-2"
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        data-testid="upload-dropzone"
      >
        {busy ? (
          <>
            <Spinner size="sm" />
            <span className="text-sm">{gettext('Reading {file}…').replace('{file}', fileName)}</span>
          </>
        ) : (
          <>
            <Icon name="upload" className="h-6 w-6" />
            <span>{gettext('Click to choose a file')}</span>
          </>
        )}
      </button>

      <div className="flex justify-end">
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
          {gettext('Cancel')}
        </button>
      </div>
    </div>
  );
};

export default Step2Upload;
