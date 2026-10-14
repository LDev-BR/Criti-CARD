// Native progressive forms: text stays text, and every write retains CSRF.
import { toast, errorMessage } from './toasts.js';
function statusFor(form) {
    const container = form.closest('[data-social-card], [data-social-user]') || form;
    return container.querySelector('[data-social-status]');
}

function showStatus(form, message, error = false) {
    if (message) toast(message, {type: error ? 'error' : 'success'});
    const status = statusFor(form);
    if (!status) return;
    status.textContent = message;
    status.hidden = !message;
    status.dataset.error = String(error);
}

function updateLikes(cardId, data) {
    document.querySelectorAll(`[data-social-card="${cardId}"]`).forEach(container => {
        const button = container.querySelector('button[aria-pressed]');
        if (button) {
            button.setAttribute('aria-pressed', String(data.liked));
            button.setAttribute('aria-label', data.liked ? 'Descurtir card' : 'Curtir card');
        }
        const desired = container.querySelector('input[name="liked"]');
        if (desired) desired.value = data.liked ? 'false' : 'true';
        const label = container.querySelector('[data-like-label]');
        if (label) label.textContent = data.liked ? 'Curtido' : 'Curtir';
        container.querySelector('[data-like-count]').textContent = String(data.like_count);
    });
}

async function refreshComments(form, data) {
    const section = form.closest('.comments-section');
    const cardId = section.querySelector('[data-card-id]').dataset.cardId;
    const response = await fetch(`/social/cards/${cardId}/comments`, { headers: { Accept: 'text/html' } });
    if (!response.ok) throw new Error('Comentário salvo. Atualize a página para ver a conversa.');
    const parsed = new DOMParser().parseFromString(await response.text(), 'text/html');
    const refreshed = parsed.querySelector('[data-comment-list]');
    if (!refreshed) throw new Error('Comentário salvo. Atualize a página para ver a conversa.');
    section.querySelector('[data-comment-list]').replaceWith(refreshed);
    section.querySelector('[data-comment-total]').textContent = String(data.comment_count);
    document.querySelectorAll(`[data-social-card="${cardId}"] [data-comment-count]`).forEach(node => { node.textContent = String(data.comment_count); });
    form.querySelector('textarea').value = '';
    showStatus(form, 'Comentário publicado.');
}

function updateUser(form, data) {
    const container = form.closest('[data-social-user]');
    container.querySelector('[data-follower-count]').textContent = String(data.follower_count);
    const follow = container.querySelector('[data-follow-button]');
    const followLabel = follow.querySelector('[data-follow-label]') || follow;
    followLabel.textContent = data.following ? 'Seguindo' : 'Seguir';
    follow.setAttribute('aria-label', data.following ? 'Deixar de seguir' : 'Seguir');
    follow.setAttribute('aria-pressed', String(data.following));
    follow.disabled = data.interaction_blocked;
    container.querySelector('input[name="following"]').value = data.following ? 'false' : 'true';
    const blockButton = container.querySelector('[data-block-button]');
    (blockButton.querySelector('[data-block-label]') || blockButton).textContent = data.blocked ? 'Desbloquear' : 'Bloquear';
    container.querySelector('input[name="blocked"]').value = data.blocked ? 'false' : 'true';
}

document.addEventListener('submit', async event => {
    const form = event.target.closest('form[data-social-form]');
    // Blocking already requires fresh server-rendered privacy state. Its native
    // redirect also carries the confirmation across that refresh.
    if (!form || event.defaultPrevented || form.dataset.socialForm === 'block' || form.hasAttribute('data-notification-action') || !form.reportValidity()) return;
    event.preventDefault();
    if (form.dataset.pending === 'true') return;
    form.dataset.pending = 'true';
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    form.setAttribute('aria-busy', 'true');
    const fields = Object.fromEntries(new FormData(form));
    const token = fields.csrf_token;
    delete fields.csrf_token;
    ['liked', 'following', 'blocked'].forEach(key => { if (key in fields) fields[key] = fields[key] === 'true'; });
    let keepDisabled = false;
    try {
        const response = await fetch(form.action, { method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRF-Token': token },
            body: JSON.stringify(fields) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Não foi possível concluir esta ação.');
        const kind = form.dataset.socialForm;
        if (kind === 'like') updateLikes(form.closest('[data-social-card]').dataset.socialCard, data);
        if (kind === 'follow') {
            updateUser(form, data);
            keepDisabled = data.interaction_blocked;
            showStatus(form, 'Preferência atualizada.');
        }
        if (kind === 'comment') await refreshComments(form, data);
        if (kind === 'delete-comment') {
            const section = form.closest('.comments-section');
            form.closest('[data-comment-id]').remove();
            const total = section.querySelector('[data-comment-total]');
            total.textContent = String(Math.max(0, Number(total.textContent) - 1));
            document.querySelectorAll(`[data-social-card="${data.card_id}"] [data-comment-count]`).forEach(node => { node.textContent = total.textContent; });
            toast('Comentário excluído.', {type:'success'});
        }
        if (kind === 'resolve-report') {
            form.closest('.social-report').querySelector('header .muted').textContent = 'Resolvida';
            form.remove();
        }
    } catch (error) {
        showStatus(form, errorMessage(error), true);
    } finally {
        form.dataset.pending = 'false';
        form.removeAttribute('aria-busy');
        button.disabled = keepDisabled;
    }
});
