import { getJson, postJson, sendJson } from '../common/http';

/**
 * The categorization rules API (`/a/{team}/{book}/bankfeed/rules/api/rules/`),
 * over the shared `common/http.js` helpers like the other page APIs: a refusal
 * throws an Error whose `payload` carries the serializer's field errors.
 */
export function rulesApi(book) {
  const base = `${book.base}bankfeed/rules/api/rules/`;
  return {
    list: () => getJson(base),
    create: (rule) => postJson(base, rule),
    update: (id, rule) => sendJson('PATCH', `${base}${id}/`, rule),
    remove: (id) => sendJson('DELETE', `${base}${id}/`),
    reorder: (ids) => postJson(`${base}reorder/`, { ids }),
    preview: (rule) => postJson(`${base}preview/`, rule),
    test: (id) => getJson(`${base}${id}/test/`),
    apply: (id) => postJson(`${base}${id}/apply/`),
    draft: (transactionId, categoryId) => {
      const params = new URLSearchParams({ transaction: transactionId });
      if (categoryId) params.set('category', categoryId);
      return getJson(`${base}draft/?${params}`);
    },
  };
}

/** Whether the page said this user may write rules (`#can-manage-rules` json_script). */
export function readCanManageRules() {
  const el = document.getElementById('can-manage-rules');
  if (!el) return false;
  try {
    return Boolean(JSON.parse(el.textContent));
  } catch {
    return false;
  }
}

/** The serializer's errors as `{field: message}`, plus `_` for the rest. */
export function fieldErrors(error) {
  const payload = error?.payload || {};
  const out = {};
  Object.entries(payload).forEach(([key, value]) => {
    if (key === 'error') return;
    const message = Array.isArray(value) ? value.join(' ') : String(value);
    out[key === 'non_field_errors' ? '_' : key] = message;
  });
  if (!Object.keys(out).length) out._ = error?.message || '';
  return out;
}
