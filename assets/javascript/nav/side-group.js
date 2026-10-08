/*
  A sidebar item with sub-items (Inbox, Budget, Reports, Accounts).

  One component, two behaviours, chosen by where the markup is rendered:
  - Inside `[data-nav-flyout]` (the desktop sidebar) the sub-items open as a
    popout to the right of the nav on hover or keyboard focus. The nav list
    itself never changes height.
  - Anywhere else (the mobile dropdown) they expand in place under the item,
    toggled by the chevron, starting open when the current page is one of them.

  The popout is `position: fixed` because the nav scrolls (`overflow-y-auto`),
  which would clip an absolutely-positioned panel.
*/

// Leaving the item for its popout crosses a gap; this is how long that may take.
const CLOSE_DELAY = 200;
// Passing over another item on the way to an open popout should not steal it.
const SWITCH_DELAY = 120;
const GAP = 6;
const MARGIN = 8;

let openGroup = null;

export default function sideGroup(startOpen = false) {
  return {
    open: false,
    flyout: false,
    panelStyle: '',
    dismissed: false,
    closeTimer: null,
    openTimer: null,

    init() {
      const nav = this.$el.closest('[data-nav-flyout]');
      this.flyout = Boolean(nav);
      this.open = !this.flyout && startOpen;
      if (this.flyout) {
        nav.addEventListener('scroll', () => this.open && this.place(), { passive: true });
      }
    },

    show() {
      clearTimeout(this.closeTimer);
      clearTimeout(this.openTimer);
      // Inbox has no sub-items until the book has a feed account.
      if (this.open || !this.$refs.panel) return;
      if (openGroup && openGroup !== this) openGroup.hide();
      openGroup = this;
      this.open = true;
      this.$nextTick(() => this.place());
    },

    hide() {
      clearTimeout(this.closeTimer);
      clearTimeout(this.openTimer);
      this.open = false;
      if (openGroup === this) openGroup = null;
    },

    place() {
      const panel = this.$refs.panel;
      const row = this.$refs.row.getBoundingClientRect();
      const nav = this.$el.closest('[data-nav-flyout]').getBoundingClientRect();
      const maxHeight = window.innerHeight - 2 * MARGIN;
      const height = Math.min(panel.offsetHeight, maxHeight);
      // Line the popout's top up with the item, then pull it up if it would run off the bottom.
      const top = Math.max(MARGIN, Math.min(row.top - MARGIN, window.innerHeight - MARGIN - height));
      this.panelStyle = `left: ${nav.right + GAP}px; top: ${top}px; max-height: ${maxHeight}px;`;
    },

    group: {
      [':class']() {
        return { 'side-group-open': this.flyout && this.open };
      },
      ['@mouseenter']() {
        if (!this.flyout) return;
        this.dismissed = false;
        clearTimeout(this.closeTimer);
        if (this.open) return;
        if (openGroup && openGroup !== this) {
          this.openTimer = setTimeout(() => this.show(), SWITCH_DELAY);
        } else {
          this.show();
        }
      },
      ['@mouseleave']() {
        if (!this.flyout) return;
        clearTimeout(this.openTimer);
        // Focus inside keeps it open: a keyboard user's popout shouldn't vanish under a stray mouse.
        if (this.$el.contains(document.activeElement)) return;
        this.closeTimer = setTimeout(() => this.hide(), CLOSE_DELAY);
      },
      ['@focusin']() {
        if (this.flyout && !this.dismissed) this.show();
      },
      ['@focusout'](event) {
        if (!this.flyout || this.$el.contains(event.relatedTarget)) return;
        this.dismissed = false;
        if (!this.$el.matches(':hover')) this.hide();
      },
      ['@keydown.escape']() {
        if (!this.flyout || !this.open) return;
        this.dismissed = true;
        this.hide();
        this.$refs.link.focus();
      },
      ['@click.outside']() {
        if (this.flyout) this.hide();
      },
    },

    toggle: {
      [':aria-expanded']() {
        return this.open.toString();
      },
      ['@click']() {
        // A tap on a touch screen fires mouseenter first, so toggling here would
        // open and shut it in one go. The popout closes on tapping elsewhere.
        if (this.flyout) {
          this.dismissed = false;
          this.show();
        } else {
          this.open = !this.open;
        }
      },
    },
  };
}
