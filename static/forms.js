import { enhanceForms, enhancePasswords, enhanceCounters } from './forms/controls.js';
import { enhanceUploads } from './forms/uploads.js';
import { enhanceCardEditor } from './forms/card-editor.js';

enhancePasswords();
enhanceCounters();
enhanceUploads();
enhanceForms();
enhanceCardEditor();

document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
        if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
});
