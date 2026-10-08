import Alpine from 'alpinejs';
import sideGroup from './nav/side-group';

window.Alpine = Alpine;
Alpine.data('sideGroup', sideGroup);
document.addEventListener('DOMContentLoaded', () => {
    Alpine.start();
});
