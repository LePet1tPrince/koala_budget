import Cookies from "js-cookie";
import {Configuration} from "api-client";


export function getApiConfiguration(serverBaseUrl) {
  return new Configuration({
    basePath: serverBaseUrl,
    headers: getApiHeaders(),
  });
}

export function getApiHeaders() {
  return {
    'X-CSRFToken': Cookies.get('csrftoken'),
  }
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
