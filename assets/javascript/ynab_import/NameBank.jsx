/* globals gettext */

import React, { useCallback, useEffect, useRef, useState } from 'react';

import Icon from '../common/Icon';
import ChipPopover from './ChipPopover';
import NewNameForm from './NewNameForm';
import PickList from './PickList';

/**
 * The list every row on a screen picks from, shown once at the top.
 *
 * Each chip carries how many rows use it, so a name nothing is in yet reads as
 * such. Clicking a chip opens its menu:
 *
 * - **Rename** -- every row using it follows. Renaming onto a name already in the
 *   list combines the two.
 * - **Move all to…** -- every row using it moves to another name, picked from the
 *   same keyboard-driven list the rows use; the chip stays, now unused.
 * - **Remove** -- only for a name no row uses.
 *
 * `onAdd(raw)` and `onRename(name, raw)` return an error message, or nothing when
 * they worked. `onReassign(name, target)` and `onRemove(name)` cannot fail.
 */
const NameBank = ({
  label,
  names,
  counts,
  removable = [],
  onRemove,
  onAdd,
  onRename,
  onReassign,
  addLabel,
  addPlaceholder,
  testId,
}) => {
  const [adding, setAdding] = useState(false);

  const add = (raw) => {
    const problem = onAdd(raw);
    if (!problem) setAdding(false);
    return problem;
  };

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={testId}>
      {label && <span className="mr-1 text-sm font-medium text-base-content/70">{label}</span>}
      {names.map((name) => (
        <NameChip
          key={name}
          name={name}
          count={counts[name] || 0}
          others={names.filter((other) => other !== name)}
          canRemove={!counts[name] && removable.includes(name)}
          onRename={onRename}
          onReassign={onReassign}
          onRemove={onRemove}
          testId={testId}
        />
      ))}
      {adding ? (
        <NewNameForm
          placeholder={addPlaceholder}
          onSubmit={add}
          onCancel={() => setAdding(false)}
          testId={testId ? `${testId}-new-form` : undefined}
        />
      ) : (
        <button
          type="button"
          className="btn btn-ghost btn-sm btn-circle border border-dashed border-base-300"
          aria-label={addLabel}
          title={addLabel}
          onClick={() => setAdding(true)}
          data-testid={testId ? `${testId}-add` : undefined}
        >
          <Icon name="plus" className="h-4 w-4" aria-hidden="true" />
        </button>
      )}
    </div>
  );
};

const MenuButton = React.forwardRef(({ icon, children, onClick, disabled, testId, tone = '' }, ref) => (
  <button
    ref={ref}
    type="button"
    role="menuitem"
    className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm hover:bg-base-200 focus:bg-base-200 focus:outline-none disabled:pointer-events-none disabled:opacity-50 ${tone}`}
    onClick={onClick}
    disabled={disabled}
    data-testid={testId}
  >
    <Icon name={icon} className="h-4 w-4 shrink-0" aria-hidden="true" />
    {children}
  </button>
));
MenuButton.displayName = 'MenuButton';

const NameChip = ({ name, count, others, canRemove, onRename, onReassign, onRemove, testId }) => {
  const [open, setOpen] = useState(false);
  // 'menu' | 'rename' | 'move'
  const [mode, setMode] = useState('menu');
  const triggerRef = useRef(null);
  const firstItemRef = useRef(null);

  const close = useCallback(() => {
    setOpen(false);
    setMode('menu');
  }, []);

  // Keyboard users land on the first action, and Tab walks the rest.
  useEffect(() => {
    if (open && mode === 'menu') firstItemRef.current?.focus();
  }, [open, mode]);

  const done = () => {
    close();
    triggerRef.current?.focus();
  };

  const rename = (raw) => {
    const problem = onRename(name, raw);
    if (!problem) close();
    return problem;
  };

  const usedBy =
    count === 1 ? gettext('Used by 1 row') : gettext('Used by {n} rows').replace('{n}', count.toLocaleString());

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`name-chip ${count === 0 ? 'is-unused' : ''}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={gettext('{name}, {usedBy}').replace('{name}', name).replace('{usedBy}', usedBy)}
        onClick={() => (open ? close() : setOpen(true))}
        data-testid={testId ? `${testId}-chip` : undefined}
        data-name={name}
      >
        <span className="truncate" title={name}>
          {name}
        </span>
        <span className="money text-xs text-base-content/70" aria-hidden="true">
          {count}
        </span>
        <Icon name="chevron-down" className="h-3 w-3 shrink-0 opacity-60" aria-hidden="true" />
      </button>
      <ChipPopover
        open={open}
        triggerRef={triggerRef}
        onClose={close}
        testId={testId ? `${testId}-chip-menu` : undefined}
      >
        {mode === 'menu' && (
          <div role="menu" aria-label={name}>
            <div className="px-3 pt-1.5 pb-1">
              <div className="truncate text-sm font-medium" title={name}>
                {name}
              </div>
              <div className="text-xs text-base-content/70">{usedBy}</div>
            </div>
            <MenuButton
              ref={firstItemRef}
              icon="pencil"
              onClick={() => setMode('rename')}
              testId={testId && `${testId}-rename`}
            >
              {gettext('Rename')}
            </MenuButton>
            <MenuButton
              icon="arrow-right-left"
              onClick={() => setMode('move')}
              disabled={count === 0 || others.length === 0}
              testId={testId && `${testId}-move`}
            >
              {count === 0
                ? gettext('Move all to…')
                : gettext('Move all {n} to…').replace('{n}', count.toLocaleString())}
            </MenuButton>
            {canRemove && (
              <MenuButton
                icon="trash"
                tone="text-error"
                onClick={() => {
                  onRemove(name);
                  close();
                }}
                testId={testId && `${testId}-remove`}
              >
                {gettext('Remove')}
              </MenuButton>
            )}
          </div>
        )}
        {mode === 'rename' && (
          <div className="p-2">
            <NewNameForm
              initialValue={name}
              placeholder={gettext('New name')}
              submitLabel={gettext('Rename')}
              onSubmit={rename}
              onCancel={() => setMode('menu')}
              testId={testId ? `${testId}-rename-form` : undefined}
            />
          </div>
        )}
        {mode === 'move' && (
          <>
            <div className="px-3 pt-1.5 text-xs text-base-content/70">
              {gettext('Move every row in “{name}” to:').replace('{name}', name)}
            </div>
            <PickList
              options={others}
              value={null}
              onPick={(target) => {
                onReassign(name, target);
                done();
              }}
              ariaLabel={gettext('Move to')}
              testId={testId ? `${testId}-move-list` : undefined}
            />
          </>
        )}
      </ChipPopover>
    </>
  );
};

export default NameBank;
