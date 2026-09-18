import React from 'react';

import { currency } from '../format';
import DeltaChip from './DeltaChip';

const StatCard = ({ label, value, delta, deltaLabel, testId, format = currency, goodIsUp = true }) => (
  <div className="app-card" data-testid={testId}>
    <div className="text-sm text-base-content/70">{label}</div>
    <div className="text-2xl font-semibold mt-1">{format(value)}</div>
    {delta !== undefined && delta !== null && (
      <div className="mt-1">
        <DeltaChip value={delta} label={deltaLabel} goodIsUp={goodIsUp} format={format} />
      </div>
    )}
  </div>
);

export default StatCard;
