import React from 'react';

import { currency } from '../format';

/**
 * A signed delta vs. some baseline, colored by whether the direction is good.
 * `goodIsUp` is false for spend-like metrics, where more is worse.
 */
const DeltaChip = ({ value, label, goodIsUp = true, format = currency }) => {
  if (value === null || value === undefined) return null;
  const up = value >= 0;
  const good = goodIsUp ? up : !up;
  const cls = good ? 'text-success' : 'text-error';
  const arrow = up ? '▲' : '▼';
  return (
    <span className={`text-xs font-medium ${cls}`}>
      {arrow} {format(Math.abs(value))}
      {label ? ` ${label}` : ''}
    </span>
  );
};

export default DeltaChip;
