// Collection actions update in place; native forms remain available without JS.
import { refreshLiveSearch, setLiveFormPending } from './live-search.js';
import { toast, errorMessage } from './toasts.js';

document.addEventListener('input', event => {
    const form = event.target.closest('[data-backlog-update]');
    if (form) form.dataset.dirty = 'true';
});
document.addEventListener('change', event => {
    const form = event.target.closest('[data-backlog-update]');
    if (form) form.dataset.dirty = 'true';
});

document.addEventListener('submit', async event => {
    const form = event.target.closest('[data-backlog-add], [data-backlog-update], [data-backlog-remove]');
    if (!form || event.defaultPrevented || !form.reportValidity()) return;
    event.preventDefault();
    if (form.dataset.pending) return;
    form.dataset.pending = 'true';
    const button = event.submitter || form.querySelector('button[type="submit"]');
    const originalLabel = button.innerHTML;
    const data = new FormData(form);
    const adding = form.hasAttribute('data-backlog-add');
    const root = form.closest('[data-live-search]');
    if (!adding) setLiveFormPending(root, form.action, true);
    const message = () => document.querySelector('[data-backlog-message]');
    button.disabled = true;
    form.setAttribute('aria-busy', 'true');
    if (!adding) button.textContent = 'Salvando…';
    try {
        const response = await fetch(form.action, { method: 'POST', body: data, credentials: 'same-origin',
            headers: { Accept: 'application/json', 'X-CSRF-Token': data.get('csrf_token') } });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Não foi possível atualizar sua coleção.');
        if (adding) {
            button.textContent = 'Em sua coleção';
            button.classList.add('catalog-added');
            if (!form.isConnected) await refreshLiveSearch(root);
        } else {
            delete form.dataset.dirty;
            form.closest('details').open = false;
            const updated = await refreshLiveSearch(root, { savedForm: form.action.replace(/\/remove$/, '/update') });
            if (!updated) throw new Error('Alteração salva. Atualize a página para conferir a coleção.');
            const itemId = result.item?.id;
            const focus = itemId && document.querySelector(`[data-backlog-item="${itemId}"] .backlog-edit summary`);
            if (document.activeElement === document.body) {
                (focus || document.querySelector('[data-live-results-heading]'))?.focus({ preventScroll: true });
            }
        }
        if (message()) message().textContent = result.message;
        toast(result.message, {type:'success'});
    } catch (error) {
        const feedback = errorMessage(error);
        if (message()) message().textContent = feedback;
        toast(feedback, {type:'error'});
        button.disabled = false;
        button.innerHTML = originalLabel;
    } finally {
        if (!adding) setLiveFormPending(root, form.action, false);
        delete form.dataset.pending;
        form.removeAttribute('aria-busy');
        if (!adding) { button.disabled = false; button.innerHTML = originalLabel; }
    }
});
