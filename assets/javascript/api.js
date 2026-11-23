import Cookies from 'js-cookie';
import { Configuration } from 'api-client';

export function getApiConfiguration(serverBaseUrl) {
  return new Configuration({
    basePath: serverBaseUrl,
    headers: getApiHeaders(),
  });
}

export function getApiHeaders() {
  return {
    'X-CSRFToken': Cookies.get('csrftoken'),
  };
}

const firstMessage = (value) => {
  const first = Array.isArray(value) ? value[0] : value;
  return typeof first === 'string' ? first : '';
};

/**
 * The user-facing reason a generated-client call failed.
 *
 * DRF answers `{"detail": "..."}` for its own errors (404, 403, a 409 refusal) and
 * `{"<field>": ["..."]}` / `{"non_field_errors": ["..."]}` for validation; a view's
 * unexpected-error handler adds `debug` (the exception itself, in DEBUG only). A
 * body with none of those -- a proxy timeout, a 413, Django's HTML 500 -- is reported
 * as what the server actually answered, which says more than "Something went wrong".
 */
export const apiErrorMessage = (payload, response) => {
  const reason =
    firstMessage(payload.detail) ||
    firstMessage(payload.non_field_errors) ||
    Object.values(payload).map(firstMessage).find(Boolean) ||
    `The server answered ${response.status} ${response.statusText}.`.trim();
  return payload.debug ? `${reason} (${payload.debug})` : reason;
};

/**
 * Await a generated-client call, turning its `ResponseError` into an `Error` whose
 * `message` is the server's reason (see `apiErrorMessage`), with `status` and the
 * parsed `payload` for callers that branch on them (a 409, a list of missing answers).
 */
export async function apiCall(request) {
  try {
    return await request;
  } catch (error) {
    const response = error?.response;
    if (!response) throw error;
    const payload = await response.json().catch(() => ({}));
    const body = payload && typeof payload === 'object' ? payload : {};
    throw Object.assign(new Error(apiErrorMessage(body, response)), { payload: body, status: response.status });
  }
}

/**
 * Await a generated-client `...Raw()` call and return its JSON body exactly as the
 * server sent it (snake_case keys, decimal strings), or null for an empty body.
 *
 * For the React apps whose components read the API's own field names: the typed
 * `...()` methods rename every key to camelCase and turn dates into `Date`s. A
 * failure is `apiCall`'s `Error` (`message`, `status`, `payload`).
 */
export async function apiJson(request) {
  const response = await apiCall(request);
  const text = await response.raw.text();
  return text ? JSON.parse(text) : null;
}

/**
 * A `YYYY-MM-DD` day as the `Date` a generated request model takes: UTC midnight,
 * which its `toISOString().substring(0, 10)` turns back into the same day in
 * every timezone. A `Date` (a picker's local midnight) keeps its local day;
 * empty is undefined.
 */
export function apiDate(value) {
  if (!value) return undefined;
  if (value instanceof Date) return new Date(Date.UTC(value.getFullYear(), value.getMonth(), value.getDate()));
  return new Date(`${String(value).slice(0, 10)}T00:00:00Z`);
}

/**
 * An API body the server embedded in the page (`<script id="{id}" type="application/json">`,
 * from `json_script`) instead of having the page fetch it, as the generated `…FromJSON`
 * types it -- the same object the matching api-client call returns. Null without one.
 * A server-rendered page does this only for a body its own view already built (see
 * `EMBEDDED_API_BODIES` in `apps/api/tests/test_api_surface.py`).
 */
export function pageData(id, fromJSON) {
  const element = document.getElementById(id);
  return element ? fromJSON(JSON.parse(element.textContent)) : null;
}
