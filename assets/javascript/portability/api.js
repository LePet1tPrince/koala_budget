import { PortabilityApi } from 'api-client';

import { apiCall, getApiConfiguration } from '../api';

/**
 * The export/import endpoints, through the generated api-client.
 *
 * The server owns every decision here too -- this only hands it a file and a
 * typed book name, and reads back what it made of them. The export and the
 * safety copy are browser downloads (plain links), so `exportUrl` and
 * `safetyExportUrl` are built here rather than fetched.
 */
export const getPortabilityApi = (book) => {
  const client = new PortabilityApi(getApiConfiguration(''));
  const { params } = book;

  return {
    exportUrl: `${book.base}data/export/`,
    safetyExportUrl: (importId) => `${book.base}data/api/safety-export/?import_id=${encodeURIComponent(importId)}`,
    state: () => apiCall(client.portabilityState(params)),
    upload: (file) => apiCall(client.portabilityUpload({ ...params, file })),
    apply: (importId, bookName) =>
      apiCall(client.portabilityApply({ ...params, dataApplyRequest: { importId, bookName } })),
    status: (importId) => apiCall(client.portabilityStatus({ ...params, importId })),
  };
};
