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

/**
 * Resolve renaming `current` in `list` to `raw`.
 *
 * Returns `{ name }` -- `unchanged` when it is the same name, `merged` when it is
 * another name already in the list (renaming onto an existing name is how two
 * are combined) -- or `{ error }`. A change of case alone is a rename, not a
 * no-op: "credit card" → "Credit Card" is exactly the fix this is for.
 */
export const resolveRename = (list, current, raw, { taken = [], takenMessage = '' } = {}) => {
  const name = cleanName(raw);
  if (!name) return { error: gettext('Give it a name.') };
  if (name === current) return { name, unchanged: true };
  const existing = findName(
    list.filter((item) => item !== current),
    name,
  );
  if (existing) return { name: existing, merged: true };
  if (findName(taken, name)) return { error: takenMessage };
  return { name };
};

/**
 * The name `name` now goes by, following renames (`{ old: new }`) to the end.
 *
 * Renames chain -- rename A to B, then B to C -- and a suggested name is listed
 * under whatever it was last renamed to. The hop limit guards against a cycle
 * (A → B, then B → A) rather than anything a user would build on purpose.
 */
export const renamed = (renames, name) => {
  let current = name;
  for (let hop = 0; hop < 20 && Object.prototype.hasOwnProperty.call(renames, current); hop += 1) {
    const next = renames[current];
    if (next === current) break;
    current = next;
  }
  return current;
};

/**
 * How the user has changed one list of names: `extra` names they added, `renames`
 * (`{ shown name: new name }`) and `hidden` names they renamed away or removed.
 *
 * The list itself is always derived -- suggested names (renamed), then extras, then
 * any other name a row uses -- so a name a row still uses can never disappear
 * from it, and a name does not jump position when a row starts using it (the
 * keyboard order in every chip menu follows this list).
 */
export const EMPTY_EDITS = Object.freeze({ extra: [], renames: {}, hidden: [] });

export const listNames = (suggested, inUse, edits = EMPTY_EDITS) => {
  const hidden = (name) => edits.hidden.includes(name);
  let names = [];
  suggested.forEach((name) => {
    const shown = renamed(edits.renames, name);
    if (!hidden(shown)) names = withName(names, shown);
  });
  edits.extra.forEach((name) => {
    if (!hidden(name)) names = withName(names, name);
  });
  inUse.forEach((name) => {
    names = withName(names, name);
  });
  return names;
};

const unhide = (edits, name) => edits.hidden.filter((item) => item !== name);

export const editsAfterAdd = (edits, name) => ({
  ...edits,
  extra: edits.extra.includes(name) ? edits.extra : [...edits.extra, name],
  hidden: unhide(edits, name),
});

/** `old` now goes by `name`; `merged` when `name` was already in the list. */
export const editsAfterRename = (edits, old, name, merged) => {
  const renames = { ...edits.renames };
  // A name renamed back to an earlier one must not loop through its old entry.
  delete renames[name];
  let { extra } = edits;
  let hidden = unhide(edits, name);
  if (extra.includes(old)) {
    // A name the user added is renamed in place, so it keeps its position.
    extra = merged ? extra.filter((item) => item !== old) : extra.map((item) => (item === old ? name : item));
  } else if (merged) {
    hidden = [...hidden, old];
  } else {
    renames[old] = name;
  }
  return { extra, renames, hidden };
};

export const editsAfterRemove = (edits, name) =>
  edits.extra.includes(name)
    ? { ...edits, extra: edits.extra.filter((item) => item !== name) }
    : { ...edits, hidden: [...edits.hidden, name] };
