import Cookies from 'js-cookie';

/**
 * The YNAB import endpoints.
 *
 * The server owns every decision: these helpers hand it files and choices and read
 * back what it made of them. Nothing here infers anything about an export.
 */
const headers = () => ({
  Accept: 'application/json',
  'X-CSRFToken': Cookies.get('csrftoken'),
});

const read = async (response) => {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    // A response with no `error` is one that never reached the view -- a crash
    // that returned Django's HTML page, a proxy timeout, a 413. "Something went
    // wrong" tells the user nothing they can act on, so say what the server
    // actually answered, and carry the server's own detail when it sent one.
    const reason = payload.error || `The server answered ${response.status} ${response.statusText}.`.trim();
    const detail = payload.detail ? ` (${payload.detail})` : '';
    throw Object.assign(new Error(`${reason}${detail}`), { payload, status: response.status });
  }
  return payload;
};

const post = async (url, body) =>
  read(
    await fetch(url, {
      method: 'POST',
      headers: { ...headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    }),
  );

export const getYnabApi = (urls) => ({
  upload: async (files) => {
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    return read(await fetch(urls.upload, { method: 'POST', headers: headers(), body: form }));
  },
  preview: (importId, choices) => post(urls.preview, { import_id: importId, choices }),
  apply: (importId, choices) => post(urls.apply, { import_id: importId, choices }),
  status: async (importId) =>
    read(await fetch(`${urls.status}?import_id=${encodeURIComponent(importId)}`, { headers: headers() })),
});
