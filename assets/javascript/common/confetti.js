// Shared canvas confetti. One volley per call; the canvas is cleaned up when the
// last particle dies. Used by the goals page celebrations and bank-feed
// categorize mode.

export const DEFAULT_COLORS = ['#ff6b6b', '#feca57', '#48dbfb', '#ff9ff3', '#54a0ff', '#5f27cd', '#01a3a4', '#f368e0'];

function makeParticle(canvas, { colors, origin, shape, emojis }) {
  const base = {
    w: Math.random() * 10 + 5,
    h: Math.random() * 6 + 3,
    color: colors[Math.floor(Math.random() * colors.length)],
    rot: Math.random() * 360,
    rotV: (Math.random() - 0.5) * 10,
    opacity: 1,
    shape,
    emoji: emojis[Math.floor(Math.random() * emojis.length)],
    size: Math.random() * 12 + 14,
  };

  if (origin === 'sky') {
    // Rain down from above the viewport
    return {
      ...base,
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height - canvas.height,
      vx: (Math.random() - 0.5) * 6,
      vy: Math.random() * 3 + 2,
    };
  }

  if (origin === 'cannons') {
    // Two streams from the bottom corners, angled inward and up
    const fromLeft = Math.random() < 0.5;
    const speed = Math.random() * 10 + 8;
    const angle = (fromLeft ? -60 : -120) + (Math.random() - 0.5) * 30; // degrees, up-and-inward
    const rad = (angle * Math.PI) / 180;
    return {
      ...base,
      x: fromLeft ? -10 : canvas.width + 10,
      y: canvas.height + 10,
      vx: Math.cos(rad) * speed * (fromLeft ? 1 : 1),
      vy: Math.sin(rad) * speed,
    };
  }

  // Point burst: origin = {x, y} in pixels
  const angle = Math.random() * Math.PI * 2;
  const speed = Math.random() * 8 + 3;
  return {
    ...base,
    x: origin.x,
    y: origin.y,
    vx: Math.cos(angle) * speed,
    vy: Math.sin(angle) * speed - 3, // bias upward
  };
}

export function createConfetti(canvas, options = {}) {
  const {
    colors = DEFAULT_COLORS,
    count = 150,
    origin = 'sky', // 'sky' | 'cannons' | {x, y} in pixels
    shape = 'rect', // 'rect' | 'leaf' | 'emoji'
    emojis = ['💵', '🪙', '💰', '🤑'],
    fadeAfter = 60,
    onDone,
  } = options;

  const ctx = canvas.getContext('2d');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;

  const particles = Array.from({ length: count }, () => makeParticle(canvas, { colors, origin, shape, emojis }));

  let frame = 0;
  let animId = null;
  const animate = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    frame++;
    let alive = false;
    particles.forEach(p => {
      p.x += p.vx;
      p.y += p.vy;
      p.vy += p.shape === 'leaf' ? 0.03 : 0.05;
      if (p.shape === 'leaf') p.vx += Math.sin((frame + p.rot) / 10) * 0.08; // flutter
      p.rot += p.rotV;
      if (frame > fadeAfter) p.opacity -= 0.01;
      if (p.opacity <= 0) return;
      alive = true;
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate((p.rot * Math.PI) / 180);
      ctx.globalAlpha = Math.max(0, p.opacity);
      if (p.shape === 'emoji') {
        ctx.font = `${p.size}px serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(p.emoji, 0, 0);
      } else if (p.shape === 'leaf') {
        ctx.fillStyle = p.color;
        ctx.beginPath();
        ctx.ellipse(0, 0, p.w / 2, p.h / 4 + 1, 0, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.fillStyle = p.color;
        ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
      }
      ctx.restore();
    });
    if (alive) {
      animId = requestAnimationFrame(animate);
    } else if (onDone) {
      onDone();
    }
  };
  animId = requestAnimationFrame(animate);

  return () => {
    if (animId) cancelAnimationFrame(animId);
  };
}

export function fireConfetti(options = {}) {
  const canvas = document.createElement('canvas');
  canvas.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:9999;';
  document.body.appendChild(canvas);
  const cancel = createConfetti(canvas, {
    ...options,
    onDone: () => {
      canvas.remove();
      if (options.onDone) options.onDone();
    },
  });
  return () => {
    cancel();
    canvas.remove();
  };
}
