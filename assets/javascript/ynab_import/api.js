import { getJson, postForm, postJson } from '../common/http';

/**
 * The YNAB import endpoints.
 *
 * The server owns every decision: these helpers hand it files and choices and read
 * back what it made of them. Nothing here infers anything about an export.
 */
export const getYnabApi = (urls) => ({
  upload: (files) => {
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    return postForm(urls.upload, form);
  },
  preview: (importId, choices) => postJson(urls.preview, { import_id: importId, choices }),
  apply: (importId, choices) => postJson(urls.apply, { import_id: importId, choices }),
  status: (importId) => getJson(`${urls.status}?import_id=${encodeURIComponent(importId)}`),
});
