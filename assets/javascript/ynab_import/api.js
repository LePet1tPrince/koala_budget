import { YnabImportApi } from 'api-client';

import { apiCall, getApiConfiguration } from '../api';

/**
 * The YNAB import endpoints, through the generated api-client.
 *
 * The server owns every decision: these helpers hand it files and choices and read
 * back what it made of them. Nothing here infers anything about an export.
 * `choices` travels as the JSON object the screens build (see `parse_choices`).
 */
export const getYnabApi = (book) => {
  const client = new YnabImportApi(getApiConfiguration(''));
  const { params } = book;

  return {
    state: () => apiCall(client.ynabImportState(params)),
    upload: (files) => apiCall(client.ynabImportUpload({ ...params, files: Array.from(files) })),
    preview: (importId, choices) =>
      apiCall(client.ynabImportPreview({ ...params, ynabChoicesRequest: { importId, choices } })),
    apply: (importId, choices) =>
      apiCall(client.ynabImportApply({ ...params, ynabChoicesRequest: { importId, choices } })),
    status: (importId) => apiCall(client.ynabImportStatus({ ...params, importId })),
  };
};
