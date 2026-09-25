/* globals gettext */

/**
 * Names the user picks from rather than types: account groups on the accounts
 * screen, income accounts on the income screen.
 *
 * Both used to be free-text fields, where "Credit Card" in one row and "Credit
 * card" or "Creditcard" in the next quietly made two groups. Now each list is
 * defined once, at the top of its screen, and every row chooses from it. These
 * helpers are the one place a new name is cleaned and matched against the list.
 */

/** A name as the server will store it: whitespace collapsed, at most 200 characters. */
export const cleanName = (value) => (value || '').replace(/\s+/g, ' ').trim().slice(0, 200);

/** The name in `list` that `name` already means, compared case-insensitively. */
export const findName = (list, name) => {
  const needle = cleanName(name).toLowerCase();
  return list.find((item) => item.toLowerCase() === needle);
};

/** `list` with `name` appended unless it is already there in some casing. */
export const withName = (list, name) => (findName(list, name) ? list : [...list, name]);

/**
 * Resolve a name the user asked to create.
 *
 * Returns `{ name, created }`, or `{ error }`. A name that already exists in the
 * list -- in any casing -- resolves to the existing one rather than making a
 * near-duplicate; that is the whole point of the list.
 */
export const resolveNewName = (list, raw, { taken = [], takenMessage = '' } = {}) => {
  const name = cleanName(raw);
  if (!name) return { error: gettext('Give it a name.') };
  const existing = findName(list, name);
  if (existing) return { name: existing, created: false };
  if (findName(taken, name)) return { error: takenMessage };
  return { name, created: true };
};
