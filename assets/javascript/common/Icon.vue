<template>
  <svg
    v-if="body"
    :class="className"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    v-html="body"
  ></svg>
</template>

<script>
import aliases from '../../icons/aliases.json';
import geometry from '../../icons/lucide.json';

/**
 * Inline SVG icon for the Vue demo components (restyle plan Phase 6).
 *
 * The Vue twin of `Icon.jsx` and the `{% icon %}` template tag: all three read
 * the same two JSON files, so the three rendering layers can't drift apart.
 */
export default {
  name: 'Icon',
  props: {
    name: {type: String, required: true},
    className: {type: String, default: 'inline-block w-4 h-4 shrink-0'},
  },
  computed: {
    body: function () {
      return geometry[aliases[this.name] || this.name] || null;
    },
  },
};
</script>
