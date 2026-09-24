/**
 * The set of books a page belongs to.
 *
 * Views emit one value, `book-base` (`/a/{team}/{book}/`), via `json_script`.
 * Every book URL the frontend builds starts from `base`, so a change to the URL
 * shape is a one-place edit; the generated api-client takes the two slugs
 * separately, which is what `params` is for: `client.someCall({ ...book.params })`.
 */
export function bookFromBase(base) {
  const [, , teamSlug = '', bookSlug = ''] = (base || '').split('/');
  return { base: base || '', teamSlug, bookSlug, params: { teamSlug, bookSlug } };
}

export function readBook(elementId = 'book-base') {
  const element = document.getElementById(elementId);
  return bookFromBase(element ? JSON.parse(element.textContent) : '');
}
