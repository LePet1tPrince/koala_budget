import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import Icon from '../../common/Icon';
import { portalTarget, useAnchoredPosition } from '../../common/popoverPosition';

/* globals gettext, interpolate */

/**
 * The rule behind a feed row's suggestion or automatic categorization: a small
 * wand button that opens a panel naming the rule and offering what can be done
 * about it -- undo an auto-post, dismiss a suggestion, or edit the rule.
 *
 * Portaled, because the category cell clips its overflow (`truncate`).
 */
export default function RuleBadge({ row, ruleMatch, editRuleUrl, onUndo, onDismiss, disabled }) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef(null);
  const panelRef = useRef(null);
  const { style, measure } = useAnchoredPosition(open, anchorRef, panelRef);
  // The first measurement runs before the panel exists; measure again once it has a size.
  useLayoutEffect(() => {
    if (open) measure();
  }, [open, measure]);
  const posted = ruleMatch.status === 'auto_posted';

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => {
      if (!panelRef.current?.contains(e.target) && !anchorRef.current?.contains(e.target)) setOpen(false);
    };
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setOpen(false);
        anchorRef.current?.focus();
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const label = posted
    ? interpolate(gettext('Categorized automatically by the rule “%s”'), [ruleMatch.ruleName])
    : interpolate(gettext('Suggested by the rule “%s”'), [ruleMatch.ruleName]);

  const act = (fn) => (e) => {
    e.stopPropagation();
    setOpen(false);
    fn?.(row);
  };

  return (
    <>
      <button
        ref={anchorRef}
        type="button"
        className={`btn btn-ghost btn-xs shrink-0 px-1 ${posted ? 'text-primary' : 'text-base-content/70'}`}
        title={label}
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="dialog"
        data-testid={`rule-badge-${row.id}`}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
      >
        <Icon name="wand-magic-sparkles" className="h-3.5 w-3.5" />
        {posted && <span className="text-[10px] font-semibold uppercase">{gettext('Auto')}</span>}
      </button>
      {open &&
        createPortal(
          <div
            ref={panelRef}
            role="dialog"
            aria-label={label}
            className="fixed z-50 w-72 rounded-xl border border-base-300 bg-base-100 p-3 text-sm shadow-lg"
            style={style ? { top: style.top, left: style.left } : { visibility: 'hidden' }}
            onClick={(e) => e.stopPropagation()}
            data-testid={`rule-panel-${row.id}`}
          >
            <p className="font-medium">{label}</p>
            {ruleMatch.heldLabel && (
              <p className="mt-1 text-warning">
                {interpolate(gettext('Not posted automatically: %s.'), [ruleMatch.heldLabel.toLowerCase()])}
              </p>
            )}
            {ruleMatch.payeeName && (
              <p className="mt-1 text-base-content/70">
                {interpolate(gettext('The rule renamed the payee to “%s”.'), [ruleMatch.payeeName])}
              </p>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              {posted ? (
                <button
                  type="button"
                  className="btn btn-xs"
                  disabled={disabled}
                  onClick={act(onUndo)}
                  data-testid={`rule-undo-${row.id}`}
                >
                  <Icon name="rotate-ccw" className="h-3.5 w-3.5" /> {gettext('Undo')}
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-xs"
                  disabled={disabled}
                  onClick={act(onDismiss)}
                  data-testid={`rule-dismiss-${row.id}`}
                >
                  {gettext('Not this time')}
                </button>
              )}
              {ruleMatch.ruleId != null && editRuleUrl && (
                <a
                  className="btn btn-ghost btn-xs"
                  href={editRuleUrl(ruleMatch.ruleId)}
                  onClick={(e) => e.stopPropagation()}
                >
                  {gettext('Edit rule')}
                </a>
              )}
            </div>
          </div>,
          portalTarget(anchorRef.current),
        )}
    </>
  );
}
