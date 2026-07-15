// Goals page: quick-assign buttons, count-up animations, and per-style
// celebrations (summit | koala | arcade). Server-rendered cards carry data
// attributes; this module wires them up.
import Cookies from 'js-cookie';
import { fireConfetti } from '../common/confetti';

const LEAF_COLORS = ['#4ade80', '#22c55e', '#16a34a', '#86efac', '#a3e635', '#65a30d'];

const props = JSON.parse(document.getElementById('goals-props')?.textContent || '{}');
const root = document.querySelector('[data-goals-root]');
const style = root?.dataset.style || 'summit';
let available = props.available || 0;
let totalSaved = props.totalSaved || 0;
let xp = props.xp || 0;

const fmt = (amount) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount);

// ---------------------------------------------------------------------------
// Number animation
// ---------------------------------------------------------------------------

function animateNumber(el, from, to, { duration = 900, jitter = false } = {}) {
  if (!el) return;
  const format = el.dataset.format || 'currency';
  const render = (value, settled) => {
    let display = value;
    if (jitter && !settled) display = value + (Math.random() - 0.5) * Math.max(Math.abs(to - from) / 50, 1);
    el.textContent = format === 'pct' ? `${Math.round(display)}%` : fmt(display);
  };
  const start = performance.now();
  const tick = (now) => {
    const t = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - t, 3);
    render(from + (to - from) * eased, t >= 1);
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// ---------------------------------------------------------------------------
// Toasts
// ---------------------------------------------------------------------------

function toast(message, kind = 'success') {
  let container = document.getElementById('goals-toast');
  if (!container) {
    container = document.createElement('div');
    container.id = 'goals-toast';
    container.className = 'toast toast-end toast-bottom';
    container.style.zIndex = '10000';
    document.body.appendChild(container);
  }
  const alert = document.createElement('div');
  alert.className = `alert alert-${kind} shadow-lg`;
  alert.setAttribute('data-testid', 'goals-toast-alert');
  alert.textContent = message;
  container.appendChild(alert);
  setTimeout(() => alert.remove(), 5000);
}

// ---------------------------------------------------------------------------
// Arcade sound (tiny WebAudio synth; off unless the user opts in)
// ---------------------------------------------------------------------------

let soundOn = localStorage.getItem('goalsSoundOn') === '1';
let audioCtx = null;

function beep(notes) {
  if (!soundOn) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    notes.forEach(([freq, at, len]) => {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = 'square';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.08, audioCtx.currentTime + at);
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + at + len);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(audioCtx.currentTime + at);
      osc.stop(audioCtx.currentTime + at + len);
    });
  } catch (e) {
    /* no audio available — stay silent */
  }
}

const COIN_SOUND = [[988, 0, 0.08], [1319, 0.08, 0.25]];
const LEVEL_UP_SOUND = [[523, 0, 0.1], [659, 0.1, 0.1], [784, 0.2, 0.1], [1047, 0.3, 0.3]];

function initSoundToggle() {
  const btn = document.querySelector('[data-sound-toggle]');
  if (!btn) return;
  const renderIcon = () => {
    btn.textContent = soundOn ? '🔊' : '🔇';
    btn.title = soundOn ? 'Mute sounds' : 'Un-mute sounds';
  };
  renderIcon();
  btn.addEventListener('click', () => {
    soundOn = !soundOn;
    localStorage.setItem('goalsSoundOn', soundOn ? '1' : '0');
    if (soundOn) beep(COIN_SOUND);
    renderIcon();
  });
}

// ---------------------------------------------------------------------------
// Celebrations
// ---------------------------------------------------------------------------

function celebrate(card, data) {
  if (style === 'koala') {
    fireConfetti({ shape: 'leaf', colors: LEAF_COLORS, origin: 'sky', count: 110 });
    const rider = card.querySelector('[data-rider]');
    if (rider) {
      rider.classList.add('koala-hop');
      setTimeout(() => rider.classList.remove('koala-hop'), 1200);
    }
  } else if (style === 'arcade') {
    root.classList.add('screen-shake');
    setTimeout(() => root.classList.remove('screen-shake'), 600);
    fireConfetti({ origin: 'cannons', count: 180 });
    fireConfetti({ origin: 'cannons', shape: 'emoji', count: 24 });
    beep(COIN_SOUND);
  } else {
    const rect = card.getBoundingClientRect();
    fireConfetti({ origin: { x: rect.left + rect.width / 2, y: rect.top + rect.height / 3 }, count: 110 });
  }

  if (data.completed) {
    setTimeout(() => fireConfetti({ origin: 'sky', count: 200 }), 300);
    const bell = card.querySelector('[data-bell]');
    if (bell) {
      bell.classList.add('bell-ring');
      setTimeout(() => bell.classList.remove('bell-ring'), 2000);
    }
    if (style === 'arcade') beep(LEVEL_UP_SOUND);
  }
}

function successMessage(data) {
  const gained = Math.round(data.new_pct) - Math.round(data.old_pct);
  if (data.completed) {
    return `🎉 ${data.goal_name} is fully funded! You did it!`;
  }
  if (style === 'koala') {
    return `🐨 +${fmt(data.assigned)} — the koala climbed to ${Math.round(data.new_pct)}%${gained > 0 ? ` (up ${gained}%)` : ''}!`;
  }
  if (style === 'arcade') {
    return `💥 SLAM! +${fmt(data.assigned)} → ${data.goal_name} hits ${Math.round(data.new_pct)}%!`;
  }
  return `+${fmt(data.assigned)} — ${data.goal_name} is now ${Math.round(data.new_pct)}% funded (was ${Math.round(data.old_pct)}%).`;
}

// ---------------------------------------------------------------------------
// Arcade XP / level bar
// ---------------------------------------------------------------------------

function arcadeLevel(points) {
  const step = props.levelStep || 500;
  const names = props.levelNames || [];
  let level = 1;
  let floor = 0;
  while (points >= floor + step * level) {
    floor += step * level;
    level += 1;
  }
  const span = step * level;
  return {
    number: level,
    name: names[Math.min(level - 1, names.length - 1)] || '',
    into: points - floor,
    span,
    pct: ((points - floor) / span) * 100,
  };
}

function updateXp(assigned) {
  const bar = document.querySelector('[data-xp-bar]');
  if (!bar) return;
  const before = arcadeLevel(xp);
  xp += Math.round(assigned);
  const after = arcadeLevel(xp);
  bar.style.width = `${after.pct}%`;
  const num = document.querySelector('[data-xp-num]');
  if (num) num.textContent = `${after.into.toLocaleString()} / ${after.span.toLocaleString()} XP`;
  const label = document.querySelector('[data-level-label]');
  if (label) label.textContent = `LV ${after.number} — ${after.name}`;
  if (after.number > before.number) {
    toast(`⬆️ LEVEL UP! Your team is now LV ${after.number}: ${after.name}`, 'info');
    fireConfetti({ origin: 'cannons', count: 150 });
    beep(LEVEL_UP_SOUND);
  }
}

// ---------------------------------------------------------------------------
// Card + page updates
// ---------------------------------------------------------------------------

function refreshAssignButtons() {
  document.querySelectorAll('[data-goal-card]').forEach((card) => {
    const btn = card.querySelector('[data-assign-all]');
    if (!btn) return;
    const remaining = parseFloat(card.dataset.remaining || '0');
    const funded = card.classList.contains('is-funded') || remaining <= 0;
    const finish = !funded && available >= remaining && remaining > 0;
    const amount = finish ? remaining : available;
    const label = finish ? btn.dataset.labelFinish : btn.dataset.labelAll;
    const labelEl = btn.querySelector('[data-assign-label]') || btn;
    labelEl.textContent = `${label} (${fmt(Math.max(amount, 0))})`;
    btn.disabled = funded || available <= 0;
  });
  document.querySelectorAll('[data-available-display]').forEach((el) => {
    el.textContent = fmt(available);
    el.classList.toggle('text-success', available > 0);
    el.classList.toggle('text-error', available < 0);
  });
  document.querySelectorAll('[data-saved-display]').forEach((el) => {
    el.textContent = fmt(totalSaved);
  });
}

function updateCard(card, data) {
  card.dataset.remaining = String(data.remaining);

  animateNumber(card.querySelector('[data-num="saved"]'), data.old_saved, data.new_saved, {
    jitter: style === 'arcade',
  });
  animateNumber(card.querySelector('[data-num="pct"]'), data.old_pct, data.new_pct);
  const remainingEl = card.querySelector('[data-num="remaining"]');
  if (remainingEl) {
    animateNumber(remainingEl, Math.max(data.remaining + data.assigned, 0), data.remaining);
  }
  const thisMonthEl = card.querySelector('[data-num="this-month"]');
  if (thisMonthEl) {
    animateNumber(thisMonthEl, data.this_month - data.assigned, data.this_month);
  }

  const fill = card.querySelector('[data-fill]');
  if (fill) fill.style.height = `${data.new_pct}%`;
  const rider = card.querySelector('[data-rider]');
  if (rider) rider.style.bottom = `${data.new_pct}%`;

  card.querySelectorAll('[data-milestone]').forEach((marker) => {
    const value = parseFloat(marker.dataset.milestone);
    const reached = data.new_pct >= value;
    if (reached && !marker.classList.contains('milestone-reached')) {
      marker.classList.add('milestone-reached', 'milestone-pop');
      setTimeout(() => marker.classList.remove('milestone-pop'), 1500);
    }
  });

  if (data.completed) {
    card.classList.add('is-funded');
    const fundedBadge = card.querySelector('[data-funded-badge]');
    if (fundedBadge) fundedBadge.hidden = false;
  }
}

// ---------------------------------------------------------------------------
// Assign flow
// ---------------------------------------------------------------------------

async function assign(card, amount) {
  const url = card.dataset.assignUrl;
  const buttons = card.querySelectorAll('[data-assign-all], [data-assign-custom]');
  buttons.forEach((b) => b.classList.add('btn-disabled'));
  try {
    const body = { month: root.dataset.month };
    if (amount != null) body.amount = amount;
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': Cookies.get('csrftoken'),
      },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      toast(data.error || 'Could not assign funds.', 'error');
      return;
    }
    available = data.new_available;
    totalSaved += data.assigned;
    updateCard(card, data);
    refreshAssignButtons();
    updateXp(data.assigned);
    celebrate(card, data);
    toast(successMessage(data), 'success');
    const input = card.querySelector('[data-custom-input]');
    if (input) input.value = '';
  } catch (e) {
    toast('Could not assign funds. Check your connection and try again.', 'error');
  } finally {
    buttons.forEach((b) => b.classList.remove('btn-disabled'));
  }
}

function init() {
  if (!root) return;
  initSoundToggle();
  refreshAssignButtons();

  document.querySelectorAll('[data-goal-card]').forEach((card) => {
    card.querySelector('[data-assign-all]')?.addEventListener('click', () => assign(card, null));

    const customBtn = card.querySelector('[data-assign-custom]');
    const customInput = card.querySelector('[data-custom-input]');
    const submitCustom = () => {
      const value = parseFloat(customInput?.value);
      if (!value || value <= 0) {
        toast('Enter an amount above zero first.', 'warning');
        return;
      }
      assign(card, value);
    };
    customBtn?.addEventListener('click', submitCustom);
    customInput?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        submitCustom();
      }
    });
  });

  // Server renders final fill heights (works without JS); replay them from zero
  // on first paint so the thermometers visibly climb.
  document.querySelectorAll('[data-fill], [data-rider]').forEach((el) => {
    const prop = el.hasAttribute('data-fill') ? 'height' : 'bottom';
    el.style.transition = 'none';
    el.style[prop] = '0%';
    void el.offsetHeight;
    el.style.transition = '';
    requestAnimationFrame(() => {
      el.style[prop] = `${el.dataset.pct}%`;
    });
  });
}

init();
