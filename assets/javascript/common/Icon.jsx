import React from 'react';

import aliases from '../../icons/aliases.json';
import geometry from '../../icons/lucide.json';

/**
 * Inline SVG icon (restyle plan Phase 6).
 *
 * Reads the same two JSON files as the `{% icon %}` template tag, so React and
 * Django templates draw from one source instead of two that drift. `name`
 * accepts a Lucide name or one of the Font Awesome aliases, so call sites
 * converted from the old font icons keep reading naturally (`name="home"`).
 */
const Icon = ({ name, className = 'inline-block w-4 h-4 shrink-0', ...rest }) => {
  const key = aliases[name] || name;
  const body = geometry[key];

  if (!body) {
    if (process.env.NODE_ENV !== 'production') {
      // eslint-disable-next-line no-console
      console.warn(`Icon: unknown name "${name}" (resolved to "${key}")`);
    }
    return null;
  }

  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      // The geometry is generated from lucide-static at author time, not user input.
      dangerouslySetInnerHTML={{ __html: body }}
      {...rest}
    />
  );
};

export default Icon;
