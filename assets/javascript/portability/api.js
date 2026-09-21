import Cookies from 'js-cookie';

/**
 * The export/import endpoints.
 *
 * Mirrors `apps/ynab_import/api.js`'s shape deliberately: same error-reading
 * convention (a response with no `error` field is one that never reached the
 * view), same CSRF header. The server owns every decision here too -- this
 * only hands it a file and a typed team name, and reads back what it made of
 * them.
 */
const headers = () => ({
  Accept: 'application/json',
  'X-CSRFToken': Cookies.get('csrftoken'),
});

const read = async (response) => {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
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

export const getPortabilityApi = (urls) => ({
  upload: async (file) => {
    const form = new FormData();
    form.append('file', file);
    return read(await fetch(urls.upload, { method: 'POST', headers: headers(), body: form }));
  },
  apply: (importId, teamName) => post(urls.apply, { import_id: importId, team_name: teamName }),
  status: async (importId) =>
    read(await fetch(`${urls.status}?import_id=${encodeURIComponent(importId)}`, { headers: headers() })),
});
