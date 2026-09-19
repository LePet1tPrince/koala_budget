/* globals gettext */

import React, { useCallback, useRef, useState } from 'react';

import Icon from '../common/Icon';

/**
 * Both CSVs at once.
 *
 * The user is never asked which file is which: the server reads the headers and
 * works it out, so a renamed export still imports and there is one fewer thing to
 * get wrong on the first screen.
 */
const Step1Upload = ({ onUpload, busy, error }) => {
  const [dragging, setDragging] = useState(false);
  const [files, setFiles] = useState([]);
  const input = useRef(null);

  const take = useCallback((list) => {
    const chosen = Array.from(list || []).filter((file) => file.name.toLowerCase().endsWith('.csv'));
    setFiles(chosen.slice(0, 2));
  }, []);

  const drop = useCallback(
    (e) => {
      e.preventDefault();
      setDragging(false);
      take(e.dataTransfer.files);
    },
    [take],
  );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{gettext('Bring your YNAB budget over')}</h2>
        <p className="mt-2 max-w-prose text-base-content/70">
          {gettext(
            'In YNAB, open your budget and choose Export budget. You will get two CSV files — a Register and a Plan. Drop both here.',
          )}
        </p>
      </div>

      <div
        className={`rounded-box border-2 border-dashed p-10 text-center transition-colors ${
          dragging ? 'border-primary bg-primary/10' : 'border-base-300 hover:border-primary/50'
        }`}
        onDragEnter={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDragOver={(e) => e.preventDefault()}
        onDrop={drop}
        data-testid="ynab-dropzone"
      >
        <Icon name="cloud-upload" className="mx-auto mb-4 h-12 w-12 shrink-0 text-base-content/70" />
        <p className="text-lg">{gettext('Drop both CSV files here')}</p>
        <p className="mt-1 text-sm text-base-content/70">{gettext('or')}</p>
        <label className="btn btn-primary mt-3">
          <Icon name="folder-open" className="mr-2 h-4 w-4 shrink-0" />
          {gettext('Choose files')}
          <input
            ref={input}
            type="file"
            className="hidden"
            accept=".csv"
            multiple
            onChange={(e) => take(e.target.files)}
            data-testid="ynab-file-input"
          />
        </label>
      </div>

      {files.length > 0 && (
        <ul className="space-y-2" data-testid="ynab-chosen-files">
          {files.map((file) => (
            <li key={file.name} className="flex items-center gap-2 text-sm">
              <Icon name="check" className="h-4 w-4 shrink-0 text-success" />
              <span className="truncate">{file.name}</span>
              <span className="text-base-content/70">{Math.round(file.size / 1024).toLocaleString()} KB</span>
            </li>
          ))}
        </ul>
      )}

      {error && (
        <div className="alert alert-error" data-testid="ynab-error">
          <span>{error}</span>
        </div>
      )}

      <div className="flex justify-end">
        <button
          type="button"
          className="btn btn-primary"
          disabled={files.length < 2 || busy}
          onClick={() => onUpload(files)}
          data-testid="ynab-upload-btn"
        >
          {busy && <span className="loading loading-spinner loading-xs"></span>}
          {gettext('Read my export')}
        </button>
      </div>
    </div>
  );
};

export default Step1Upload;
