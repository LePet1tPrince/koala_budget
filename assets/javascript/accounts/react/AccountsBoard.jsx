import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import Cookies from 'js-cookie';

import { formatCurrency } from '../../utilities/currency';

// ---------------------------------------------------------------------------
// id helpers: dnd-kit ids are strings namespaced by kind
// ---------------------------------------------------------------------------
const accountDndId = (id) => `account-${id}`;
const groupDndId = (id) => `group-${id}`;
const groupDropId = (id) => `group-drop-${id}`;

async function postJson(url, body) {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': Cookies.get('csrftoken'),
    },
    body: JSON.stringify(body),
  });
  let data = {};
  try {
    data = await response.json();
  } catch {
    // non-JSON error page; fall through to the generic message
  }
  if (!response.ok) {
    throw new Error(data.error || gettext('Something went wrong. Please try again.'));
  }
  return data;
}

const GripIcon = () => (
  <svg width="10" height="16" viewBox="0 0 10 16" fill="currentColor" aria-hidden="true">
    {[1, 8].map((x) =>
      [2, 8, 14].map((y) => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.5" />)
    )}
  </svg>
);

const PlusIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
    <path d="M7 1v12M1 7h12" />
  </svg>
);

// ---------------------------------------------------------------------------
// Inline "+" form used for both new accounts and new groups
// ---------------------------------------------------------------------------
function InlineCreateForm({ placeholder, onSubmit, onCancel, extraAction }) {
  const [name, setName] = useState('');
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const submit = async () => {
    if (!name.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSubmit(name.trim());
      setName('');
      inputRef.current?.focus();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="px-2 py-1.5">
      <div className="flex items-center gap-2">
        <input
          ref={inputRef}
          type="text"
          className="input input-bordered input-sm flex-1"
          placeholder={placeholder}
          value={name}
          maxLength={200}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              submit();
            } else if (e.key === 'Escape') {
              onCancel();
            }
          }}
        />
        <button type="button" className="btn btn-primary btn-sm" disabled={!name.trim() || saving} onClick={submit}>
          {saving ? <span className="loading loading-spinner loading-xs" /> : gettext('Add')}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>
          {gettext('Cancel')}
        </button>
      </div>
      <div className="flex justify-between items-center mt-1">
        {error ? (
          <span className="text-xs text-error">{error}</span>
        ) : (
          <span className="text-xs text-base-content/50">{gettext('Enter to add · Esc to close')}</span>
        )}
        {extraAction}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Account row (sortable)
// ---------------------------------------------------------------------------
function AccountRowContent({ account, dragHandleProps, dragging, overlay }) {
  return (
    <div
      className={[
        'group/row flex items-center gap-1 rounded-lg px-2 py-2 transition-colors',
        overlay ? 'bg-base-100 shadow-lg ring-1 ring-primary/40 rotate-1' : 'hover:bg-base-200',
        dragging ? 'opacity-40' : '',
      ].join(' ')}
      data-testid="account-row"
    >
      <button
        type="button"
        className={[
          'touch-none shrink-0 cursor-grab active:cursor-grabbing rounded p-1 text-base-content/40',
          'hover:text-base-content hover:bg-base-300 transition-all',
          overlay ? 'opacity-100' : 'opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100',
        ].join(' ')}
        aria-label={gettext('Drag to reorder or move to another group')}
        data-testid="account-drag-handle"
        {...dragHandleProps}
      >
        <GripIcon />
      </button>
      <div className="min-w-0 flex-1">
        <a href={account.url} className="font-medium truncate block hover:link" data-testid="account-name" draggable={false}>
          {account.name}
        </a>
        {(account.institution || account.hasFeed) && (
          <div className="text-xs text-base-content/60 truncate flex items-center gap-1.5">
            {account.institution && <span>{account.institution}</span>}
            {account.hasFeed && (
              <span className="tooltip tooltip-right" data-tip={gettext('Linked to a bank feed')}>
                <i className="fa fa-link" aria-hidden="true"></i>
              </span>
            )}
          </div>
        )}
      </div>
      <span className="font-mono text-sm shrink-0 tabular-nums">{formatCurrency(account.balance)}</span>
    </div>
  );
}

function SortableAccountRow({ account, groupId, accountType }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: accountDndId(account.id),
    data: { kind: 'account', account, groupId, accountType },
  });

  return (
    <li ref={setNodeRef} style={{ transform: CSS.Translate.toString(transform), transition }}>
      <AccountRowContent account={account} dragging={isDragging} dragHandleProps={{ ...attributes, ...listeners }} />
    </li>
  );
}

// ---------------------------------------------------------------------------
// Group card (sortable within its type section, droppable for accounts)
// ---------------------------------------------------------------------------
function GroupCard({ group, accountType, urls, onCreateAccount, isDropTarget, draggingAccount }) {
  const [adding, setAdding] = useState(false);
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: groupDndId(group.id),
    data: { kind: 'group', group, accountType },
  });

  const subtotal = group.accounts.reduce((sum, a) => sum + parseFloat(a.balance || 0), 0);
  const createPageUrl = `${urls.accountCreatePage}?account_type=${accountType}&account_group=${group.id}`;

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={[
        'card bg-base-100 border transition-all',
        isDropTarget ? 'border-primary ring-2 ring-primary/30' : 'border-base-300',
        isDragging ? 'opacity-40' : '',
      ].join(' ')}
      data-testid="account-group-card"
    >
      <div className="group/hdr flex items-center gap-1 px-3 pt-2.5 pb-1.5">
        <button
          type="button"
          className={[
            'touch-none shrink-0 cursor-grab active:cursor-grabbing rounded p-1 text-base-content/40',
            'hover:text-base-content hover:bg-base-300 transition-all opacity-0 group-hover/hdr:opacity-100 focus-visible:opacity-100',
          ].join(' ')}
          aria-label={gettext('Drag to reorder this group')}
          data-testid="group-drag-handle"
          {...attributes}
          {...listeners}
        >
          <GripIcon />
        </button>
        <a href={group.url} className="font-semibold hover:link truncate" data-testid="group-name" draggable={false}>
          {group.name}
        </a>
        <span className="badge badge-ghost badge-sm shrink-0">{group.accounts.length}</span>
        <span className="ml-auto font-mono text-sm text-base-content/70 tabular-nums shrink-0">
          {formatCurrency(subtotal)}
        </span>
      </div>

      <SortableContext items={group.accounts.map((a) => accountDndId(a.id))} strategy={verticalListSortingStrategy}>
        <ul className="px-1.5 pb-1">
          {group.accounts.map((account) => (
            <SortableAccountRow key={account.id} account={account} groupId={group.id} accountType={accountType} />
          ))}
          {group.accounts.length === 0 && (
            <li
              className={[
                'mx-2 my-1 rounded-lg border border-dashed px-3 py-3 text-center text-sm transition-colors',
                isDropTarget ? 'border-primary text-primary' : 'border-base-300 text-base-content/40',
              ].join(' ')}
            >
              {draggingAccount ? gettext('Drop account here') : gettext('No accounts yet')}
            </li>
          )}
        </ul>
      </SortableContext>

      <div className="px-1.5 pb-1.5">
        {adding ? (
          <InlineCreateForm
            placeholder={gettext('New account name')}
            onSubmit={(name) => onCreateAccount(group.id, name)}
            onCancel={() => setAdding(false)}
            extraAction={
              <a href={createPageUrl} className="text-xs link link-hover text-base-content/50">
                {gettext('More options…')}
              </a>
            }
          />
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="w-full flex items-center justify-center gap-1.5 rounded-lg border border-dashed border-transparent px-2 py-1.5 text-sm text-base-content/40 transition-colors hover:border-base-300 hover:bg-base-200 hover:text-base-content"
            data-testid="add-account-btn"
            title={gettext('Add an account to this group')}
          >
            <PlusIcon />
            {gettext('Add account')}
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Type section (Assets, Liabilities, …)
// ---------------------------------------------------------------------------
function TypeSection({ section, urls, onCreateAccount, onCreateGroup, dropTargetGroupId, draggingAccount, dimmed }) {
  const [adding, setAdding] = useState(false);

  return (
    <section
      className={['transition-opacity', dimmed ? 'opacity-40' : ''].join(' ')}
      data-testid="account-type-section"
      data-account-type={section.key}
    >
      <h2 className="text-sm font-semibold uppercase tracking-wide text-base-content/60 mb-2">{section.label}</h2>
      <SortableContext items={section.groups.map((g) => groupDndId(g.id))} strategy={verticalListSortingStrategy}>
        <div className="flex flex-col gap-3">
          {section.groups.map((group) => (
            <GroupCard
              key={group.id}
              group={group}
              accountType={section.key}
              urls={urls}
              onCreateAccount={onCreateAccount}
              isDropTarget={dropTargetGroupId === group.id}
              draggingAccount={draggingAccount}
            />
          ))}
        </div>
      </SortableContext>
      <div className="mt-3">
        {adding ? (
          <div className="card bg-base-100 border border-base-300">
            <InlineCreateForm
              placeholder={gettext('New group name')}
              onSubmit={(name) => onCreateGroup(section.key, name)}
              onCancel={() => setAdding(false)}
            />
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="w-full flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-base-300 px-2 py-2.5 text-sm text-base-content/50 transition-colors hover:border-primary hover:text-primary hover:bg-primary/5"
            data-testid="add-group-btn"
            title={gettext('Add a group to this section')}
          >
            <PlusIcon />
            {interpolate(gettext('New %s group'), [section.label.toLowerCase()])}
          </button>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Board
// ---------------------------------------------------------------------------
export default function AccountsBoard({ types: initialTypes, urls }) {
  const [types, setTypes] = useState(initialTypes);
  const [active, setActive] = useState(null); // {kind, account|group, accountType, groupId?}
  const [overGroupId, setOverGroupId] = useState(null);
  const [toast, setToast] = useState(null);
  const snapshotRef = useRef(null); // state at drag start, for revert on error/cancel
  const sourceGroupIdRef = useRef(null);
  const toastTimerRef = useRef(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  // Only consider drop targets that make sense for what is being dragged:
  // groups only land on sibling groups; accounts land on rows or group cards
  // of the same account type. Without this, closestCorners happily picks an
  // account row as the "closest" target for a group drag and the drop no-ops.
  const collisionDetection = (args) => {
    const activeData = args.active.data.current || {};
    const droppableContainers = args.droppableContainers.filter((container) => {
      const data = container.data.current || {};
      if (data.accountType !== activeData.accountType) return false;
      if (activeData.kind === 'group') return data.kind === 'group';
      return data.kind === 'account' || data.kind === 'group';
    });
    return closestCorners({ ...args, droppableContainers });
  };

  const showToast = (message, kind = 'success') => {
    clearTimeout(toastTimerRef.current);
    setToast({ message, kind });
    toastTimerRef.current = setTimeout(() => setToast(null), kind === 'error' ? 6000 : 2200);
  };
  useEffect(() => () => clearTimeout(toastTimerRef.current), []);

  // ----- state lookup helpers ------------------------------------------------
  const findGroupLocation = (state, groupId) => {
    for (const section of state) {
      const index = section.groups.findIndex((g) => g.id === groupId);
      if (index !== -1) return { section, index, group: section.groups[index] };
    }
    return null;
  };

  const findAccountLocation = (state, accountId) => {
    for (const section of state) {
      for (const group of section.groups) {
        const index = group.accounts.findIndex((a) => a.id === accountId);
        if (index !== -1) return { section, group, index, account: group.accounts[index] };
      }
    }
    return null;
  };

  // Resolve what the pointer is over into a target group (for account drags)
  const resolveTargetGroup = (over) => {
    if (!over) return null;
    const data = over.data.current || {};
    if (data.kind === 'account') return { groupId: data.groupId, accountType: data.accountType, overAccount: data.account };
    if (data.kind === 'group') return { groupId: data.group.id, accountType: data.accountType, overAccount: null };
    return null;
  };

  // ----- drag lifecycle -------------------------------------------------------
  const handleDragStart = ({ active: activeItem }) => {
    const data = activeItem.data.current || {};
    snapshotRef.current = types;
    sourceGroupIdRef.current = data.groupId ?? null;
    setActive(data);
  };

  const revert = () => {
    if (snapshotRef.current) setTypes(snapshotRef.current);
  };

  const handleDragCancel = () => {
    revert();
    setActive(null);
    setOverGroupId(null);
  };

  const handleDragOver = ({ active: activeItem, over }) => {
    const activeData = activeItem.data.current || {};
    if (activeData.kind !== 'account') return;

    const target = resolveTargetGroup(over);
    if (!target || target.accountType !== activeData.accountType) {
      setOverGroupId(null);
      return;
    }
    setOverGroupId(target.groupId);

    const current = findAccountLocation(types, activeData.account.id);
    if (!current || current.group.id === target.groupId) return;

    // Move the account into the hovered group (position resolved on drop)
    setTypes((state) => {
      const from = findAccountLocation(state, activeData.account.id);
      const to = findGroupLocation(state, target.groupId);
      if (!from || !to) return state;

      const movedAccount = from.account;
      let insertIndex = to.group.accounts.length;
      if (target.overAccount) {
        const overIndex = to.group.accounts.findIndex((a) => a.id === target.overAccount.id);
        if (overIndex !== -1) insertIndex = overIndex;
      }

      return state.map((section) => ({
        ...section,
        groups: section.groups.map((group) => {
          if (group.id === from.group.id) {
            return { ...group, accounts: group.accounts.filter((a) => a.id !== movedAccount.id) };
          }
          if (group.id === to.group.id) {
            const accounts = [...group.accounts];
            accounts.splice(insertIndex, 0, movedAccount);
            return { ...group, accounts };
          }
          return group;
        }),
      }));
    });
  };

  const handleDragEnd = async ({ active: activeItem, over }) => {
    const activeData = activeItem.data.current || {};
    setActive(null);
    setOverGroupId(null);

    if (activeData.kind === 'group') {
      await endGroupDrag(activeData, over);
    } else if (activeData.kind === 'account') {
      await endAccountDrag(activeData, over);
    }
    snapshotRef.current = null;
  };

  const endGroupDrag = async (activeData, over) => {
    const overData = over?.data.current || {};
    if (overData.kind !== 'group' || overData.accountType !== activeData.accountType) return;
    if (overData.group.id === activeData.group.id) return;

    let orderedIds = null;
    const nextState = types.map((section) => {
      if (section.key !== activeData.accountType) return section;
      const fromIndex = section.groups.findIndex((g) => g.id === activeData.group.id);
      const toIndex = section.groups.findIndex((g) => g.id === overData.group.id);
      if (fromIndex === -1 || toIndex === -1) return section;
      const groups = arrayMove(section.groups, fromIndex, toIndex);
      orderedIds = groups.map((g) => g.id);
      return { ...section, groups };
    });
    if (!orderedIds) return;
    setTypes(nextState);

    try {
      await postJson(urls.reorderGroups, { account_type: activeData.accountType, group_ids: orderedIds });
      showToast(gettext('Order saved'));
    } catch (e) {
      revert();
      showToast(e.message, 'error');
    }
  };

  const endAccountDrag = async (activeData, over) => {
    const accountId = activeData.account.id;
    const sourceGroupId = sourceGroupIdRef.current;

    // Final in-container reposition (cross-group moves already applied in onDragOver)
    let finalState = types;
    const target = resolveTargetGroup(over);
    const current = findAccountLocation(types, accountId);
    if (!current) return;

    if (target && target.accountType === activeData.accountType && target.groupId === current.group.id && target.overAccount) {
      const overIndex = current.group.accounts.findIndex((a) => a.id === target.overAccount.id);
      if (overIndex !== -1 && overIndex !== current.index) {
        finalState = types.map((section) => ({
          ...section,
          groups: section.groups.map((group) =>
            group.id === current.group.id
              ? { ...group, accounts: arrayMove(group.accounts, current.index, overIndex) }
              : group
          ),
        }));
        setTypes(finalState);
      }
    }

    // Persist the source and destination groups' full order
    const finalLocation = findAccountLocation(finalState, accountId);
    if (!finalLocation) return;

    const changedGroupIds = new Set([finalLocation.group.id]);
    if (sourceGroupId != null && sourceGroupId !== finalLocation.group.id) changedGroupIds.add(sourceGroupId);

    // Nothing moved?
    const before = findAccountLocation(snapshotRef.current || finalState, accountId);
    if (before && before.group.id === finalLocation.group.id && before.index === finalLocation.index) return;

    const groupsPayload = [];
    for (const section of finalState) {
      for (const group of section.groups) {
        if (changedGroupIds.has(group.id)) {
          groupsPayload.push({ group_id: group.id, account_ids: group.accounts.map((a) => a.id) });
        }
      }
    }

    try {
      await postJson(urls.reorderAccounts, { groups: groupsPayload });
      showToast(
        sourceGroupId !== finalLocation.group.id
          ? interpolate(gettext('Moved to %s'), [finalLocation.group.name])
          : gettext('Order saved')
      );
    } catch (e) {
      revert();
      showToast(e.message, 'error');
    }
  };

  // ----- inline creates -------------------------------------------------------
  const createAccount = async (groupId, name) => {
    const data = await postJson(urls.createAccount, { name, group_id: groupId });
    setTypes((state) =>
      state.map((section) => ({
        ...section,
        groups: section.groups.map((group) =>
          group.id === groupId ? { ...group, accounts: [...group.accounts, data.account] } : group
        ),
      }))
    );
    showToast(interpolate(gettext('Account "%s" created'), [data.account.name]));
  };

  const createGroup = async (accountType, name) => {
    const data = await postJson(urls.createGroup, { name, account_type: accountType });
    setTypes((state) =>
      state.map((section) =>
        section.key === accountType ? { ...section, groups: [...section.groups, data.group] } : section
      )
    );
    showToast(interpolate(gettext('Group "%s" created'), [data.group.name]));
  };

  const draggingAccount = active?.kind === 'account';

  const overlayContent = useMemo(() => {
    if (!active) return null;
    if (active.kind === 'account') {
      return (
        <div className="w-72">
          <AccountRowContent account={active.account} overlay dragHandleProps={{}} />
        </div>
      );
    }
    return (
      <div className="card bg-base-100 shadow-lg ring-1 ring-primary/40 rotate-1 px-3 py-2 w-72">
        <div className="flex items-center gap-2">
          <span className="text-base-content/40"><GripIcon /></span>
          <span className="font-semibold truncate">{active.group.name}</span>
          <span className="badge badge-ghost badge-sm ml-auto">{active.group.accounts.length}</span>
        </div>
      </div>
    );
  }, [active]);

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={collisionDetection}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-8 gap-y-8 items-start">
        {types.map((section) => (
          <TypeSection
            key={section.key}
            section={section}
            urls={urls}
            onCreateAccount={createAccount}
            onCreateGroup={createGroup}
            dropTargetGroupId={draggingAccount ? overGroupId : null}
            draggingAccount={draggingAccount}
            dimmed={draggingAccount && active.accountType !== section.key}
          />
        ))}
      </div>

      <DragOverlay dropAnimation={{ duration: 180 }}>{overlayContent}</DragOverlay>

      {toast && (
        <div className="toast toast-end z-50">
          <div className={`alert ${toast.kind === 'error' ? 'alert-error' : 'alert-success'} shadow-lg py-2`} data-testid="board-toast">
            <span>{toast.message}</span>
          </div>
        </div>
      )}
    </DndContext>
  );
}
