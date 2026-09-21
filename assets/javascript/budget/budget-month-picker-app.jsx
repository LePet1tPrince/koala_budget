'use strict';

import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { format } from 'date-fns';

import BudgetMonthPicker from './react/BudgetMonthPicker';
import { monthFromLocation, swapRoot, swapToMonth } from './month-swap';

const el = document.getElementById('budget-month-picker');

// The abbreviated month, in a trigger wide enough to hold any of them, so the
// prev/next chevrons either side sit still instead of sliding in and out as the
// month changes — "May" to "September" moved them noticeably. The width has
// slack in it: the label is centred, so extra room spreads evenly and the
// chevrons stay put whatever the label does.
const LABEL_PROPS = {
  labelFormat: 'MMM yyyy',
  triggerClassName: 'btn btn-ghost btn-sm text-lg font-bold min-w-[8rem]',
};

/**
 * The picker, with the budget page's in-place month change wired up.
 *
 * The month lives here rather than in the picker so the label can update the
 * instant it is clicked — the content underneath arrives a moment later, and a
 * button that waits for the network before showing what you picked feels
 * broken. It also has to survive Back and Forward: those move the address bar
 * without reloading the document, so the label would otherwise disagree with
 * both the URL and the figures on screen.
 *
 * Pages without a swap region (Goals) fall through to the picker's own full
 * navigation, which is all they need.
 */
const MonthPickerApp = ({ initialMonth }) => {
  const [month, setMonth] = useState(initialMonth);

  useEffect(() => {
    const onPopState = () => {
      const target = monthFromLocation() || initialMonth;
      setMonth(target);
      swapToMonth(target, { push: false });
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [initialMonth]);

  const handleNavigate = (date) => {
    const target = format(date, 'yyyy-MM-dd');
    setMonth(target);
    swapToMonth(target);
  };

  return <BudgetMonthPicker initialMonth={month} onNavigate={handleNavigate} {...LABEL_PROPS} />;
};

if (el) {
  const initialMonth = el.dataset.month;
  if (swapRoot()) {
    createRoot(el).render(<MonthPickerApp initialMonth={initialMonth} />);
  } else {
    createRoot(el).render(<BudgetMonthPicker initialMonth={initialMonth} {...LABEL_PROPS} />);
  }
}
