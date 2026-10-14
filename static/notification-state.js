/** One revision for all unread-count writers; older requests cannot restore old counts. */
let revision = 0;
export const notificationRevision = () => revision;
export const invalidateNotificationCount = () => ++revision;

export function setNotificationCount(count) {
    if (!Number.isInteger(count) || count < 0) return;
    revision++;
    document.querySelectorAll('[data-unread-count]').forEach(node => {
        node.textContent = String(count);
        if (node.closest('.site-header')) node.hidden = count === 0;
    });
    document.querySelector('[data-notification-link]')?.setAttribute('aria-label',
        count ? `Notificações, ${count} não lidas` : 'Notificações, todas lidas');
}
