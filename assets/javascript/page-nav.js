// Site-wide link behaviours, wired by attribute so server-rendered pages need no
// per-page script.
//
// [data-back-link] -- an in-page "Back to X" link. When the page we came from *is*
// X, following the href would push X again, so the browser's Back button would
// then return here and the two pages ping-pong. Going back through history
// instead lands on the real entry (scroll position and all). Anything else --
// no referrer, a new tab, a different referrer -- follows the href as usual.
//
// [data-dialog] -- a link that opens the <dialog> it names instead of navigating.
// The href stays the no-JS fallback (the standalone edit/delete page).

function isPlainClick(event) {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

function cameFrom(href) {
  if (window.history.length < 2 || !document.referrer) return false;
  try {
    const referrer = new URL(document.referrer);
    const target = new URL(href, window.location.href);
    return (
      referrer.origin === window.location.origin &&
      referrer.pathname === target.pathname &&
      target.pathname !== window.location.pathname
    );
  } catch {
    return false;
  }
}

document.addEventListener('click', (event) => {
  if (event.defaultPrevented || !isPlainClick(event)) return;

  const dialogLink = event.target.closest('[data-dialog]');
  if (dialogLink) {
    const dialog = document.getElementById(dialogLink.dataset.dialog);
    if (dialog && typeof dialog.showModal === 'function') {
      event.preventDefault();
      dialog.showModal();
      const field = dialog.querySelector('[autofocus], input:not([type=hidden]), textarea, select');
      if (field) field.focus();
    }
    return;
  }

  const backLink = event.target.closest('a[data-back-link]');
  if (backLink && cameFrom(backLink.href)) {
    event.preventDefault();
    window.history.back();
  }
});
