import React, { useEffect } from 'react';

import { fireConfetti } from '../../common/confetti';
import StatCard from '../parts/StatCard';

/** Step 9: that's the month -- headline recap, then on to the permanent dashboard. */
const StepRecap = ({ review, onFinish }) => {
  useEffect(() => {
    // 'sky' and 'cannons' are the only named origins the module knows; anything
    // else is read as an {x, y} point and yields NaN.
    const cancel = fireConfetti({ origin: 'cannons' });
    return cancel;
  }, []);

  const { current } = review;

  return (
    <div className="text-center">
      <h2 className="text-xl font-semibold mb-4">{review.month_label} is in the books.</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Money in" value={current.income} testId="recap-income" />
        <StatCard label="Money out" value={current.spend} testId="recap-spend" />
        <StatCard label="Saved" value={current.saved} testId="recap-saved" />
        <StatCard label="Left over" value={current.net} testId="recap-net" />
      </div>
      <button type="button" className="btn btn-primary" onClick={onFinish} data-testid="open-dashboard-btn">
        Open the month dashboard &rarr;
      </button>
    </div>
  );
};

export default StepRecap;
