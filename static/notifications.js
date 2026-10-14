/** Private, visibility-aware counters and progressively enhanced read actions. */
import { toast, errorMessage } from './toasts.js';
import { refreshLiveSearch } from './live-search.js';
import { notificationRevision, invalidateNotificationCount, setNotificationCount } from './notification-state.js';

const bell = document.querySelector('[data-notification-link]');
let latest = null;
let latestAt = null;
let writes = 0;
let request = null;
let stopped = false;
let timer = null;

export function updateNotificationCount(count, latestId = null, createdAt = null) {
    if (!Number.isInteger(count) || count < 0) return;
    if (Number.isInteger(latestId) && latestId >= 0) latest = latestId;
    if (createdAt === null || Number.isFinite(Date.parse(createdAt))) latestAt = createdAt;
    setNotificationCount(count);
}

async function refreshCounter(announce = true) {
    if (!bell || stopped || document.hidden || !navigator.onLine || writes || request) return;
    const current = notificationRevision();
    const controller = new AbortController(); request = controller;
    const deadline = setTimeout(() => controller.abort(), 8000);
    try {
        const response = await fetch(bell.dataset.notificationStatusUrl, {
            credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' }, signal: controller.signal });
        if ([401,403].includes(response.status)) { stopped = true; return; }
        if (!response.ok) return;
        const data = await response.json();
        if (current !== notificationRevision() || !Number.isInteger(data.latest_id) || !Number.isInteger(data.unread_count)) return;
        const arrived = latest !== null && data.unread_count > 0 &&
            (data.latest_id > latest || (latestAt !== null && Date.parse(data.latest_at) > Date.parse(latestAt)));
        updateNotificationCount(data.unread_count, data.latest_id, data.latest_at);
        if (arrived && announce && !document.hidden) toast('Você tem novas notificações na comunidade.', {
            type: 'info', action: { label: 'Ver notificações', href: bell.href } });
    } catch (_) { /* Background failures keep the last valid count and never interrupt editing. */ }
    finally { clearTimeout(deadline); request = null; }
}
function scheduleCounter() {
    clearTimeout(timer);
    if (!bell || stopped) return;
    timer = setTimeout(async () => { await refreshCounter(); scheduleCounter(); }, 30000);
}
if (bell) {
    refreshCounter(false).finally(scheduleCounter);
    for (const name of ['focus','online']) window.addEventListener(name, () => refreshCounter());
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) { clearTimeout(timer); request?.abort(); }
        else { refreshCounter().finally(scheduleCounter); }
    });
    window.addEventListener('pagehide', () => { clearTimeout(timer); request?.abort(); });
    window.addEventListener('pageshow', event => { if (event.persisted) { stopped = false; refreshCounter(false).finally(scheduleCounter); } });
}
document.addEventListener('criticard:notifications-count', event => {
    updateNotificationCount(Number(event.detail.count), event.detail.latestId ?? null, event.detail.latestAt ?? null);
});

function localTimes() {
    const now = Date.now();
    const relative = new Intl.RelativeTimeFormat('pt-BR', { numeric: 'auto' });
    const full = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'medium', timeStyle: 'short' });
    for (const time of document.querySelectorAll('[data-notification-time]')) {
        const date = new Date(time.dateTime);
        if (!Number.isFinite(date.getTime())) continue;
        const minutes = Math.max(0, Math.floor((now-date.getTime())/60000));
        time.textContent = minutes < 1 ? 'Agora' : minutes < 60 ? relative.format(-minutes,'minute')
            : minutes < 1440 ? relative.format(-Math.floor(minutes/60),'hour') : full.format(date);
        time.title = full.format(date);
    }
}
localTimes();
document.addEventListener('criticard:results-updated', localTimes);

document.addEventListener('submit', async event => {
    const form = event.target.closest('form[data-notification-action]');
    if (!form || event.defaultPrevented || !form.reportValidity()) return;
    event.preventDefault();
    if (form.dataset.pending) return;
    form.dataset.pending = 'true'; form.setAttribute('aria-busy','true');
    const button = event.submitter || form.querySelector('button[type=submit]');
    button.disabled = true;
    const current = invalidateNotificationCount(); writes++; request?.abort();
    try {
        const fields = new FormData(form);
        const response = await fetch(form.action, { method:'POST', body:fields, credentials:'same-origin',
            headers:{Accept:'application/json','X-CSRF-Token':fields.get('csrf_token')} });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Não foi possível atualizar a leitura.');
        if (current === notificationRevision()) updateNotificationCount(data.unread_count, data.latest_id, data.latest_at);
        const root = document.querySelector('[data-notification-center]');
        if (root && !await refreshLiveSearch(root,{history:'replace',fallbackPage:true})) {
            toast('Leitura salva. Atualize a lista para conferir as notificações.', {type:'warning'});
        } else {
            toast(form.dataset.notificationAction === 'read-all' ? 'Notificações marcadas como lidas.' : 'Notificação marcada como lida.', {type:'success'});
            if (document.activeElement === document.body) root?.querySelector('[data-live-results-heading]')?.focus({preventScroll:true});
        }
    } catch (error) {
        toast(errorMessage(error), {type:'error'});
    } finally {
        writes--; delete form.dataset.pending; form.removeAttribute('aria-busy'); button.disabled = false;
        if (!writes) refreshCounter(false);
    }
});
