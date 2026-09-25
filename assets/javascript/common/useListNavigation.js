import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Keyboard movement through a list whose focus stays somewhere else — a search
 * box above the list, typically — so typing keeps filtering while the arrows move
 * a highlight.
 *
 * Shared by the CSV wizard's `AccountComboBox` and the YNAB import's chip menus,
 * which are the same pattern: a trigger, a panel with a search box, a highlighted
 * option, and Enter to take it.
 *
 * - ↑/↓ move the highlight. `wrap` (default on) runs off either end onto the other.
 * - `tabCycles`: Tab / Shift+Tab move it too, instead of leaving the search box.
 *   Off, Tab is the caller's (the CSV wizard closes its panel and lets focus move on).
 * - Enter calls `onPick(index)` with the highlighted index.
 * - `scrollKey`: when it changes the highlighted option is scrolled into view again
 *   (pass the panel's open state, so reopening shows the current choice).
 *
 * The highlight is clamped where it is read, not chased with an effect, so a list
 * that shrinks under it (the user typed) never points past its end.
 */
const useListNavigation = (count, { wrap = true, tabCycles = false, scrollKey } = {}) => {
  const [active, setActiveRaw] = useState(0);
  const items = useRef([]);

  const current = count > 0 ? Math.min(Math.max(active, 0), count - 1) : -1;

  const setActive = useCallback((index) => setActiveRaw(index), []);

  useEffect(() => {
    if (current >= 0) items.current[current]?.scrollIntoView?.({ block: 'nearest' });
  }, [current, scrollKey]);

  const move = (step) => {
    setActiveRaw((i) => {
      const from = Math.min(Math.max(i, 0), count - 1);
      const next = from + step;
      if (wrap) return (next + count) % count;
      return Math.min(Math.max(next, 0), count - 1);
    });
  };

  /** Handle a keydown from the element that holds focus. Returns true if it was ours. */
  const onKeyDown = (e, { onPick } = {}) => {
    if (count === 0) return false;
    const tab = tabCycles && e.key === 'Tab';
    if (e.key === 'ArrowDown' || (tab && !e.shiftKey)) {
      e.preventDefault();
      move(1);
      return true;
    }
    if (e.key === 'ArrowUp' || (tab && e.shiftKey)) {
      e.preventDefault();
      move(-1);
      return true;
    }
    if (e.key === 'Enter' && onPick) {
      e.preventDefault();
      onPick(current);
      return true;
    }
    return false;
  };

  /** Spread onto each option: keeps it scrolled into view and follows the pointer. */
  const itemProps = (index) => ({
    ref: (node) => {
      items.current[index] = node;
    },
    'data-active': index === current ? 'true' : undefined,
    onMouseEnter: () => setActiveRaw(index),
  });

  return { active: current, setActive, onKeyDown, itemProps };
};

export default useListNavigation;
