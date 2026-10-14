/** Shared, text-only feedback. Native flashes remain usable without JavaScript. */
const region = document.querySelector('[data-toast-region]');
const stack = region?.querySelector('[data-toast-stack]');
const queue = [];
const active = new Set();
const entries = new Map();
let lastFocus = null;
const titles = { success: 'Tudo certo', error: 'Não foi possível concluir', warning: 'Atenção', info: 'Aviso' };
const paths = { success: 'm5 12 4 4L19 6', error: 'm8 8 8 8m0-8-8 8', warning: 'M12 8v5m0 3v.1', info: 'M12 11v6m0-10v.1' };

function icon(type) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [name, value] of Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
        'stroke-width': '1.8', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' })) svg.setAttribute(name, value);
    const circle = document.createElementNS(svg.namespaceURI, 'circle');
    for (const [name,value] of Object.entries({cx:'12',cy:'12',r:'9'})) circle.setAttribute(name,value);
    const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('d', paths[type]);
    svg.append(circle, path); return svg;
}

function schedule(entry) {
    clearTimeout(entry.timer);
    if (!entry.duration || entry.pauses.size || !entry.node) return;
    entry.started = performance.now();
    entry.timer = setTimeout(() => dismiss(entry), Math.max(1, entry.remaining));
}
function pause(entry, reason) {
    if (!entry.pauses.size && entry.started != null) entry.remaining = Math.max(0, entry.remaining - (performance.now()-entry.started));
    entry.started = null; entry.pauses.add(reason); clearTimeout(entry.timer);
    if (entry.node) entry.node.dataset.paused = 'true';
}
function resume(entry, reason) {
    entry.pauses.delete(reason);
    if (entry.node) entry.node.dataset.paused = String(entry.pauses.size > 0);
    schedule(entry);
}
function dismiss(entry) {
    if (!entry || entries.get(entry.key) !== entry) return;
    const focused = entry.node?.contains(document.activeElement);
    clearTimeout(entry.timer); entry.node?.remove(); active.delete(entry); entries.delete(entry.key);
    const queued = queue.indexOf(entry);
    if (queued !== -1) queue.splice(queued, 1);
    pump();
    if (focused) {
        const destination = lastFocus?.isConnected && !lastFocus.disabled ? lastFocus : document.getElementById('main');
        destination?.focus({ preventScroll: true });
    }
}
function pump() {
    while (stack && active.size < 3 && queue.length) {
        const entry = queue.shift();
        const node = document.createElement('article'); node.className = `toast flash ${entry.type}`;
        node.dataset.toast = ''; node.dataset.tone = entry.type;
        const mark = document.createElement('span'); mark.className = 'toast-icon'; mark.append(icon(entry.type));
        const content = document.createElement('div'); content.className = 'toast-content';
        const title = document.createElement('strong'); title.textContent = titles[entry.type];
        const message = document.createElement('p'); message.textContent = entry.message; content.append(title, message);
        if (entry.action) {
            const link = document.createElement('a'); link.className = 'toast-action';
            link.href = entry.action.href; link.textContent = entry.action.label; content.append(link);
        }
        const close = document.createElement('button'); close.type = 'button'; close.className = 'toast-close';
        close.setAttribute('aria-label', 'Fechar aviso'); close.textContent = '×'; close.addEventListener('click', () => dismiss(entry));
        node.append(mark, content, close);
        if (entry.duration) {
            const progress = document.createElement('span'); progress.className = 'toast-progress';
            progress.setAttribute('aria-hidden', 'true'); node.append(progress);
            node.style.setProperty('--toast-duration', `${entry.duration}ms`);
        }
        entry.node = node; active.add(entry);
        node.addEventListener('mouseenter', () => pause(entry, 'hover'));
        node.addEventListener('mouseleave', () => resume(entry, 'hover'));
        node.addEventListener('focusin', () => pause(entry, 'focus'));
        node.addEventListener('focusout', event => { if (!node.contains(event.relatedTarget)) resume(entry, 'focus'); });
        stack.append(node);
        if (document.hidden) pause(entry, 'hidden');
        schedule(entry);
        region.querySelector(entry.type === 'error' ? '[data-toast-alert]' : '[data-toast-status]').textContent = `${titles[entry.type]}. ${entry.message}`;
    }
}

export function toast(message, options = {}) {
    if (!stack || typeof message !== 'string' || !message.trim()) return null;
    const type = Object.hasOwn(titles, options.type) ? options.type : 'info';
    let action = null;
    if (options.action?.label && (options.action.href || options.action.url)) {
        try {
            const url = new URL(options.action.href || options.action.url, location.href);
            if (url.origin === location.origin && ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) action = { href: url.href, label: String(options.action.label) };
        } catch (_) { /* Malformed links never break a notice. */ }
    }
    const text = message.trim(); const key = `${type}\0${text}\0${action?.href || ''}`;
    const existing = entries.get(key);
    if (existing) return { dismiss: () => dismiss(existing) };
    const requested = Number.isFinite(options.duration) && options.duration >= 0 ? options.duration : Math.min(16000, text.length*45);
    const duration = type === 'error' || type === 'warning' || requested === 0 ? 0 : Math.max(6000, requested);
    const entry = { key, type, message: text, action, duration, remaining: duration, pauses: new Set() };
    entries.set(key, entry); queue.push(entry); pump();
    return { dismiss: () => dismiss(entry) };
}
export function errorMessage(error, fallback = 'Verifique sua conexão e tente novamente.') {
    return error instanceof TypeError || error instanceof SyntaxError ? fallback : error?.message || fallback;
}
function avoidDuplicateAnnouncements() {
    if (!stack) return;
    document.querySelectorAll('[data-connections-status], [data-backlog-message], [data-reward-status], [data-journey-status], [data-social-status]')
        .forEach(node => node.setAttribute('aria-live','off'));
}
avoidDuplicateAnnouncements();
document.addEventListener('criticard:results-updated', avoidDuplicateAnnouncements);
document.addEventListener('focusin', event => { if (!region?.contains(event.target)) lastFocus = event.target; });
document.addEventListener('visibilitychange', () => { for (const entry of active) document.hidden ? pause(entry, 'hidden') : resume(entry, 'hidden'); });
const source = document.querySelector('[data-toast-source]');
if (source && stack) {
    stack.classList.add('flashes');
    for (const message of source.querySelectorAll('[data-toast-message]')) toast(message.textContent, { type: message.dataset.toastType });
    source.remove();
}
