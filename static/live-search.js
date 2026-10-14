/** Progressive GET navigation: server filters, stable focus, latest response wins. */
import { notificationRevision, setNotificationCount } from './notification-state.js';
const controllers = new WeakMap();

function currentControls(address, root, navigating = false) {
    const current = new URL(location.href);
    for (const form of root.querySelectorAll('form')) {
        if (form.method.toLowerCase() !== 'get' || new URL(form.action).pathname !== address.pathname) continue;
        for (const control of form.elements) {
            if (!control.name || control.disabled || !control.matches('input:not([type="hidden"]), select')) continue;
            if (navigating && address.searchParams.get(control.name) !== current.searchParams.get(control.name)) continue;
            const value = control.value.trim();
            if (value) address.searchParams.set(control.name, value);
            else address.searchParams.delete(control.name);
        }
    }
    return address;
}

function formAddress(form) {
    const address = new URL(form.action, location.href);
    address.search = '';
    for (const [name, value] of new FormData(form)) {
        if (typeof value === 'string' && value.trim()) address.searchParams.append(name, value.trim());
    }
    address.searchParams.delete('page');
    return currentControls(address, form.closest('[data-live-search]'));
}

function rememberedFocus(body) {
    const node = document.activeElement;
    if (!body.contains(node)) return null;
    return { id: node.id, href: node.closest('a')?.getAttribute('href'),
        start: node.selectionStart, end: node.selectionEnd, direction: node.selectionDirection };
}

function restoreFocus(body, focus) {
    if (!focus) return;
    const node = focus.id ? body.querySelector('#' + CSS.escape(focus.id))
        : [...body.querySelectorAll('a')].find(link => link.getAttribute('href') === focus.href);
    if (!node) return;
    node.focus({ preventScroll: true });
    if (typeof focus.start === 'number' && node.setSelectionRange) {
        node.setSelectionRange(focus.start, focus.end, focus.direction);
    }
}

// Update siblings around the focused control without detaching its ancestors.
// Keeping the native input connected avoids closing the mobile keyboard.
function replaceAroundFocus(current, incoming, active, restoreControls = false) {
    if (!active?.id || !current.contains(active)) {
        current.replaceChildren(...incoming.childNodes);
        return;
    }
    if (current === active) {
        if (restoreControls && 'value' in current) current.value = incoming.value;
        return;
    }
    const oldBranch = [...current.children].find(node => node.contains(active));
    const newNodes = [...incoming.childNodes];
    const newBranch = newNodes.find(node => node.nodeType === 1 &&
        (node.id === active.id || node.querySelector('#' + CSS.escape(active.id))));
    if (!oldBranch || !newBranch || oldBranch.tagName !== newBranch.tagName) {
        current.replaceChildren(...newNodes);
        return;
    }
    for (const node of [...current.childNodes]) if (node !== oldBranch) node.remove();
    let after = false;
    for (const node of newNodes) {
        if (node === newBranch) { after = true; continue; }
        if (after) current.append(node);
        else current.insertBefore(node, oldBranch);
    }
    for (const attribute of [...oldBranch.attributes]) {
        if (!newBranch.hasAttribute(attribute.name)) oldBranch.removeAttribute(attribute.name);
    }
    for (const attribute of newBranch.attributes) oldBranch.setAttribute(attribute.name, attribute.value);
    replaceAroundFocus(oldBranch, newBranch, active, restoreControls);
}

class LiveSearch {
    constructor(root) {
        this.root = root;
        this.body = root.querySelector('[data-live-body]');
        this.status = root.querySelector('[data-live-status]');
        this.retry = root.querySelector('[data-live-retry]');
        this.open = root.querySelector('[data-live-open]');
        this.sequence = 0;
        this.drafts = new Map();
        this.pendingForms = new Set();
        this.typingEntry = false;
        this.requested = new URL(location.href);
        this.root.setAttribute('aria-busy', 'false');
        root.dataset.liveReady = 'true';
        this.retry.addEventListener('click', () => this.load(this.requested, { history: 'push', focusSearch: true }));
        root.addEventListener('compositionstart', () => { this.composing = true; this.cancel(); });
        root.addEventListener('compositionend', event => {
            this.composing = false;
            this.onInput(event);
        });
        root.addEventListener('input', event => this.onInput(event));
        root.addEventListener('change', event => {
            const form = this.searchForm(event.target);
            if (!form || event.target.type === 'search' || this.composing) return;
            if (!form.reportValidity()) { this.cancel(); return; }
            this.typingEntry = false;
            this.load(formAddress(form), { history: 'push' });
        });
        root.addEventListener('submit', event => {
            const form = this.searchForm(event.target);
            if (!form || !form.reportValidity()) return;
            event.preventDefault();
            this.typingEntry = false;
            this.load(formAddress(form), { history: 'push' });
        });
        root.addEventListener('click', event => {
            const link = event.target.closest('a[href]');
            if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey
                || event.shiftKey || event.altKey || link.target || link.hasAttribute('download')
                || link.hasAttribute('data-live-native')) return;
            const address = new URL(link.href);
            if (address.origin !== location.origin || address.pathname !== location.pathname || address.hash) return;
            event.preventDefault();
            this.typingEntry = false;
            if (!link.hasAttribute('data-live-reset') && !link.matches('.admin-clear, .connections-result a')
                && !link.closest('.empty-state, .connections-empty')) currentControls(address, this.root, true);
            this.load(address, { history: 'push', pagination: link.closest('.pagination') !== null,
                resetDisclosures: link.hasAttribute('data-live-reset') });
        });
        window.addEventListener('popstate', () => {
            this.typingEntry = false;
            this.load(new URL(location.href), { history: 'none', restoreControls: true });
        });
        window.addEventListener('pagehide', () => this.cancel());
    }

    searchForm(node) {
        const form = node.closest('form');
        return form?.method.toLowerCase() === 'get' && this.body.contains(form) ? form : null;
    }

    cancel() {
        clearTimeout(this.timer);
        this.sequence++;
        this.abort?.abort();
        this.root.setAttribute('aria-busy', 'false');
    }

    onInput(event) {
        const form = this.searchForm(event.target);
        if (!form || this.composing || event.isComposing) return;
        this.cancel();
        if (!form.checkValidity()) return;
        this.requested = formAddress(form);
        this.timer = setTimeout(() => this.load(this.requested, { history: 'typing' }),
            event.target.value === '' ? 0 : 260);
    }

    async load(address, options = {}) {
        this.cancel();
        const sequence = this.sequence;
        const notificationSequence = notificationRevision();
        this.requested = new URL(address);
        const abort = this.abort = new AbortController();
        this.root.setAttribute('aria-busy', 'true');
        this.root.dataset.liveState = 'loading';
        this.status.textContent = 'Atualizando resultados…';
        this.retry.hidden = true;
        this.open.hidden = true;
        try {
            const get = () => fetch(address, { credentials: 'same-origin', cache: 'no-store',
                headers: { Accept: 'text/html' }, signal: abort.signal });
            let response = await get();
            if (sequence !== this.sequence) return false;
            if (response.status === 404 && options.fallbackPage && Number(address.searchParams.get('page')) > 1) {
                address = new URL(address);
                address.searchParams.set('page', '1');
                this.requested = address;
                response = await get();
            }
            if (!response.ok) throw new Error('Busca indisponível.');
            const parsed = new DOMParser().parseFromString(await response.text(), 'text/html');
            if (sequence !== this.sequence) return false;
            const replacement = [...parsed.querySelectorAll('[data-live-search]')]
                .find(node => node.dataset.liveSearch === this.root.dataset.liveSearch)?.querySelector('[data-live-body]');
            if (!replacement || (response.url && new URL(response.url).pathname !== address.pathname)) {
                throw new Error('Sua sessão pode ter expirado. Abra a busca novamente.');
            }
            const focus = rememberedFocus(this.body);
            const disclosures = [...this.body.querySelectorAll('[data-responsive-disclosure]')].map(node => node.open);
            // Keep unrelated collection drafts while changing filters or refreshing saved progress.
            for (const form of this.body.querySelectorAll('[data-backlog-update]')) {
                if (form.dataset.dirty) this.drafts.set(form.action, [...new FormData(form)]);
            }
            if (options.savedForm) this.drafts.delete(options.savedForm);
            this.root.dispatchEvent(new CustomEvent('criticard:results-removing', { bubbles: true }));
            replaceAroundFocus(this.body, replacement, document.activeElement, options.restoreControls);
            this.body.querySelectorAll('[data-responsive-disclosure]').forEach((node, i) => {
                node.open = options.resetDisclosures
                    ? node.hasAttribute('data-keep-open') || !window.matchMedia('(max-width:850px)').matches
                    : disclosures[i] ?? node.open;
            });
            for (const [action, values] of this.drafts) {
                const form = [...this.body.querySelectorAll('[data-backlog-update]')].find(form => form.action === action);
                if (!form) continue;
                form.dataset.dirty = 'true';
                form.closest('details').open = true;
                for (const [name, value] of values) {
                    const control = form.elements.namedItem(name);
                    if (name !== 'csrf_token' && control && control.value !== value) control.value = value;
                }
            }
            for (const form of this.body.querySelectorAll('[data-backlog-update], [data-backlog-remove]')) {
                if (this.pendingForms.has(form.action)) {
                    form.dataset.pending = 'true';
                    form.inert = true;
                    form.setAttribute('aria-busy', 'true');
                    form.querySelector('button[type="submit"]').disabled = true;
                }
            }
            this.root.dispatchEvent(new CustomEvent('criticard:results-updated', { bubbles: true }));
            restoreFocus(this.body, focus);
            if (options.focusSearch && document.activeElement === document.body) {
                this.body.querySelector('input[type="search"]')?.focus({ preventScroll: true });
            }
            document.title = parsed.title;
            if (options.history !== 'none' && address.href !== location.href) {
                const replace = options.history === 'replace' || (options.history === 'typing' && this.typingEntry);
                history[replace ? 'replaceState' : 'pushState'](null, '', address);
                this.typingEntry = options.history === 'typing';
            }
            const count = this.body.querySelector('[data-live-count]')?.dataset.liveCount;
            this.status.textContent = Number(count) === 0 ? 'Nenhum resultado encontrado.'
                : `${count || ''} ${count === '1' ? 'resultado encontrado' : 'resultados encontrados'}.`;
            this.root.dataset.liveState = 'ready';
            for (const selector of ['[data-friend-requests]']) {
                const badge = parsed.querySelector(selector);
                if (badge) document.querySelectorAll(selector).forEach(node => {
                    node.textContent = badge.textContent;
                    node.hidden = badge.hidden;
                });
            }
            const unread = parsed.querySelector('[data-unread-count]');
            if (unread && notificationSequence === notificationRevision()) setNotificationCount(Number(unread.textContent));
            if (options.pagination) {
                const heading = this.body.querySelector('[data-live-results-heading]');
                heading?.focus({ preventScroll: true });
                heading?.scrollIntoView({ block: 'start' });
            }
            return true;
        } catch (error) {
            if (sequence !== this.sequence || error.name === 'AbortError') return false;
            this.root.dataset.liveState = 'error';
            this.status.textContent = 'Não foi possível atualizar. Os resultados anteriores foram mantidos. ' +
                (error.message.includes('sessão') ? error.message : 'Tente novamente ou abra a busca.');
            this.retry.hidden = false;
            this.open.href = this.requested.href;
            this.open.hidden = false;
            return false;
        } finally {
            if (sequence === this.sequence) this.root.setAttribute('aria-busy', 'false');
        }
    }
}

document.querySelectorAll('[data-live-search]').forEach(root => controllers.set(root, new LiveSearch(root)));

export function refreshLiveSearch(root, options = {}) {
    const controller = controllers.get(root);
    const history = controller?.requested.href === location.href ? 'none' : 'typing';
    return controller ? controller.load(controller.requested, { history, ...options }) : Promise.resolve(false);
}

export function setLiveFormPending(root, action, pending) {
    const controller = controllers.get(root);
    if (!controller) return;
    if (pending) controller.pendingForms.add(action);
    else controller.pendingForms.delete(action);
    for (const form of root.querySelectorAll('form')) {
        if (form.action !== action) continue;
        form.inert = pending;
        if (!pending) {
            delete form.dataset.pending;
            form.removeAttribute('aria-busy');
            form.querySelector('button[type="submit"]').disabled = false;
        }
    }
}
