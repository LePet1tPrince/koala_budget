/* globals gettext */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import Coachmark from './Coachmark';

/**
 * Phase D: the guided tasks, over the real app.
 *
 * The rail sits on every app page while the walkthrough is in its task phase. It
 * does not decide anything — `api/tasks/` returns each task's state and the reason
 * for any lock, and the rail renders that. The server is authoritative because the
 * gates are real: the opening-balance endpoint refuses a team with no journal
 * entries whatever the UI happens to show.
 *
 * Docked bottom-right rather than as a third column: the app shell is a sticky
 * 248px sidebar beside a capped content column, and a third column would fight
 * the `shrink-0` that stops a wide table squeezing the nav.
 */

const LOCKED = 'locked';
const DONE = 'done';

const TaskRow = ({ task, index, current }) => {
  const locked = task.state === LOCKED;
  const done = task.state === DONE;

  const body = (
    <>
      <span className={`rail-marker ${done ? 'is-done' : ''} ${locked ? 'is-locked' : ''}`} aria-hidden="true">
        {done ? <i className="fa fa-check"></i> : locked ? <i className="fa fa-lock"></i> : index + 1}
      </span>
      <span className="min-w-0">
        <span className={`block text-sm ${done ? 'line-through opacity-60' : ''}`}>{task.label}</span>
        {locked && task.reason && <span className="block text-xs text-base-content/70">{task.reason}</span>}
        {!locked && !done && current && task.blurb && (
          <span className="block text-xs text-base-content/70">{task.blurb}</span>
        )}
      </span>
    </>
  );

  if (locked || done) {
    return (
      <li className="rail-row" data-testid={`task-${task.slug}`} data-state={task.state}>
        {body}
      </li>
    );
  }

  return (
    <li>
      <a
        href={task.url}
        className={`rail-row rail-row-link ${current ? 'is-current' : ''}`}
        data-testid={`task-${task.slug}`}
        data-state={task.state}
      >
        {body}
      </a>
    </li>
  );
};

const TaskRail = ({ props }) => {
  const { tasksUrl, taskUrl, path, csrf } = props;

  const [tasks, setTasks] = useState([]);
  const [active, setActive] = useState(true);
  const [open, setOpen] = useState(true);
  const [coachDismissed, setCoachDismissed] = useState(false);

  const post = useCallback(
    async (body) => {
      const response = await fetch(taskUrl, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify(body),
      });
      if (!response.ok) return null;
      return response.json();
    },
    [taskUrl, csrf],
  );

  const load = useCallback(async () => {
    try {
      const response = await fetch(tasksUrl, { headers: { Accept: 'application/json' } });
      if (!response.ok) return;
      const data = await response.json();
      setTasks(data.tasks);
      setActive(data.active);
    } catch {
      // The rail is an overlay on a working app. If it cannot reach the server it
      // stays as it is rather than surfacing an error over whatever the user is doing.
    }
  }, [tasksUrl]);

  useEffect(() => {
    load();
  }, [load]);

  // The first task that is neither done nor locked — what the rail points at.
  const currentTask = useMemo(() => tasks.find((t) => t.state !== DONE && t.state !== LOCKED), [tasks]);

  const onTargetPage = currentTask && path.startsWith(currentTask.url);

  /*
    A task the server cannot detect ("go and look at the report") completes by the
    user arriving on its page.

    Checked against every open task rather than just the current one: the tasks are
    a suggested order, not a rail the user is locked into, and someone who opens
    the report while their budget is still half-written has plainly done the "see
    where the money went" step.
  */
  const arrivedAt = useMemo(
    () => tasks.find((t) => !t.auto && t.state !== DONE && t.state !== LOCKED && path.startsWith(t.url)),
    [tasks, path],
  );

  useEffect(() => {
    if (!arrivedAt) return undefined;
    let cancelled = false;
    post({ slug: arrivedAt.slug }).then((data) => {
      if (data && !cancelled) {
        setTasks(data.tasks);
        setActive(data.active);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [arrivedAt, post]);

  const dismiss = useCallback(async () => {
    setActive(false);
    await post({ action: 'dismiss' });
  }, [post]);

  if (!active || tasks.length === 0) return null;

  const doneCount = tasks.filter((t) => t.state === DONE).length;

  return (
    <>
      <aside className={`task-rail ${open ? '' : 'is-collapsed'}`} data-testid="task-rail">
        <div className="task-rail-head">
          <button
            type="button"
            className="flex min-w-0 flex-1 items-center gap-2 text-left"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            data-testid="task-rail-toggle"
          >
            <i className={`fa fa-chevron-${open ? 'down' : 'up'} text-xs text-base-content/45`}></i>
            <span className="truncate text-sm font-medium">{gettext('Get set up')}</span>
            <span className="ml-auto shrink-0 text-xs text-base-content/70">
              {doneCount}/{tasks.length}
            </span>
          </button>
          <button
            type="button"
            className="rail-close"
            onClick={dismiss}
            aria-label={gettext('Dismiss setup guide')}
            data-testid="task-rail-dismiss"
          >
            <i className="fa fa-times"></i>
          </button>
        </div>

        {open && (
          <ol className="task-rail-list">
            {tasks.map((task, i) => (
              <TaskRow key={task.slug} task={task} index={i} current={task.slug === currentTask?.slug} />
            ))}
          </ol>
        )}
      </aside>

      {open && onTargetPage && currentTask?.anchor && !coachDismissed && (
        <Coachmark
          selector={currentTask.anchor}
          text={currentTask.blurb || currentTask.label}
          onDismiss={() => setCoachDismissed(true)}
        />
      )}
    </>
  );
};

export default TaskRail;
