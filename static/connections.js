/** Connection actions progressively update server-rendered, public fragments. */
import { refreshLiveSearch } from './live-search.js';
import { toast, errorMessage } from './toasts.js';
import { notificationRevision, setNotificationCount } from './notification-state.js';

function announce(message, error = false) {
    const status = document.querySelector('[data-connections-status]');
    if (!status) return;
    status.hidden = !message;
    status.textContent = message;
    status.dataset.error = String(error);
}

function updateBadge(counts) {
    if (!counts) return;
    document.querySelectorAll('[data-friend-requests]').forEach(node => {
        node.textContent = String(counts.incoming);
        node.hidden = counts.incoming === 0;
    });
}

function completion(action, kind) {
    if (kind === 'follow') return 'Preferência de seguir atualizada.';
    return { request: 'Solicitação enviada.', accept: 'Amizade aceita. Uma boa conversa começa por aqui.',
        decline: 'Solicitação recusada.', cancel: 'Solicitação cancelada.', remove: 'Amizade desfeita.' }[action] || 'Conexões atualizadas.';
}

let refreshSequence = 0;
async function refreshFragment(personId, kind) {
    const live = document.querySelector('[data-live-search="connections"]');
    if (live) {
        const updated = await refreshLiveSearch(live, { history: 'replace', fallbackPage: true });
        if (!updated) throw new Error('Ação registrada. Atualize a página para conferir suas conexões.');
        const row = live.querySelector(`[data-connection-row="${personId}"]`);
        if (document.activeElement === document.body) {
            (row?.querySelector('.connection-identity') || live.querySelector('#connections-title'))?.focus({ preventScroll: true });
        }
        return;
    }
    const sequence = ++refreshSequence;
    const notificationSequence = notificationRevision();
    const address = new URL(window.location.href);
    const get = () => fetch(address, { credentials: 'same-origin', headers: { Accept: 'text/html' } });
    let response = await get();
    if (response.status === 404 && address.pathname === '/conexoes' && Number(address.searchParams.get('page')) > 1) {
        address.searchParams.set('page', '1');
        response = await get();
    }
    if (!response.ok) throw new Error('Ação registrada. Atualize a página para conferir a lista.');
    const parsed = new DOMParser().parseFromString(await response.text(), 'text/html');
    if (sequence !== refreshSequence) return;
    const old = document.querySelector('[data-connections-fragment]');
    const replacement = parsed.querySelector('[data-connections-fragment]');
    if (!old || !replacement) throw new Error('Ação registrada. Atualize a página para conferir suas conexões.');
    const sections = old.querySelector('[data-responsive-disclosure]');
    if (sections) replacement.querySelector('[data-responsive-disclosure]').open = sections.open;
    old.replaceWith(replacement);
    if (address.href !== window.location.href) window.history.replaceState(null, '', address);
    const badge = parsed.querySelector('[data-friend-requests]');
    if (badge) updateBadge({ incoming: Number(badge.textContent) });
    const notificationBadge = parsed.querySelector('[data-unread-count]');
    if (notificationBadge && notificationSequence === notificationRevision()) setNotificationCount(Number(notificationBadge.textContent));
    const row = replacement.querySelector(`[data-connection-row="${personId}"]`);
    const focus = row?.querySelector('.connection-identity') || (kind === 'follow' && replacement.querySelector('[data-follow-button]'))
        || replacement.querySelector('#connections-title');
    focus?.focus({ preventScroll: true });
}

document.addEventListener('submit', async event => {
    const form = event.target.closest('form[data-connection-form]');
    if (!form || !form.reportValidity()) return;
    event.preventDefault();
    if (form.dataset.pending) return;
    form.dataset.pending = 'true';
    form.setAttribute('aria-busy', 'true');
    const button = event.submitter || form.querySelector('button[type="submit"]');
    button.disabled = true;
    const fields = Object.fromEntries(new FormData(form));
    const csrf = fields.csrf_token;
    delete fields.csrf_token;
    if ('following' in fields) fields.following = fields.following === 'true';
    announce('Atualizando…');
    try {
        const response = await fetch(form.getAttribute('action'), { method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRF-Token': csrf },
            body: JSON.stringify(fields) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Não foi possível concluir esta ação.');
        updateBadge(data.counts);
        await refreshFragment(form.closest('[data-social-user]')?.dataset.socialUser, form.dataset.connectionForm);
        const message = completion(fields.action, form.dataset.connectionForm);
        announce(message);
        toast(message, {type:'success'});
    } catch (error) {
        const message = errorMessage(error);
        announce(message, true);
        toast(message, {type:'error'});
    } finally {
        delete form.dataset.pending;
        form.removeAttribute('aria-busy');
        button.disabled = false;
    }
});

document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('.connection-options[open]').forEach(menu => {
        menu.open = false;
        menu.querySelector('summary')?.focus();
    });
});
