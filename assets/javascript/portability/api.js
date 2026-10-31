import { getJson, postForm, postJson } from '../common/http';

/**
 * The export/import endpoints.
 *
 * The server owns every decision here too -- this only hands it a file and a
 * typed book name, and reads back what it made of them.
 */
export const getPortabilityApi = (urls) => ({
  upload: (file) => {
    const form = new FormData();
    form.append('file', file);
    return postForm(urls.upload, form);
  },
  apply: (importId, bookName) => postJson(urls.apply, { import_id: importId, book_name: bookName }),
  status: (importId) => getJson(`${urls.status}?import_id=${encodeURIComponent(importId)}`),
});
