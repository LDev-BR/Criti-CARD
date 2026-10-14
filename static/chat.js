/** Persistent messages, deduplicated acknowledgements and reconnect recovery. */
import { revealContent } from './motion.js';
import { enhanceContacts, enhanceConversationList } from './chat/contacts.js';

enhanceContacts();
enhanceConversationList();

const thread = document.querySelector('[data-chat-conversation]');
if (thread) enhanceChat(thread);

function enhanceChat(root) {
    const conversationId = Number(root.dataset.chatConversation);
    const userId = Number(root.dataset.chatUser);
    const endpoint = `/mensagens/${conversationId}`;
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
    const messages = root.querySelector('[data-chat-messages]');
    const form = root.querySelector('[data-chat-form]');
    const status = root.querySelector('[data-chat-status]');
    const error = root.querySelector('[data-chat-error]');
    const older = root.querySelector('[data-chat-older]');
    const readForm = root.querySelector('[data-chat-read]');
    const newMessages = root.querySelector('[data-chat-new-messages]');
    const textarea = form?.elements.body;
    const button = form?.querySelector('[type="submit"]');
    const buttonLabel = form?.querySelector('[data-chat-send-label]');
    const counter = form?.querySelector('[data-chat-counter]');
    const sendStatus = form?.querySelector('[data-chat-send-status]');
    const rendered = new Map([...messages.querySelectorAll('[data-message-id]')].map(node => [Number(node.dataset.messageId), node]));
    let latest = Math.max(0, ...rendered.keys());
    let lastRead = Number(root.dataset.chatLastRead || 0);
    const initialLatest = Number(root.dataset.chatInitialLatest || latest);
    const unreadIds = new Set([...rendered].filter(([id, node]) => id > lastRead && !node.classList.contains('is-own')).map(([id]) => id));
    let unseenUnread = Math.max(0, Number(root.dataset.chatUnread || 0) - unreadIds.size);
    let pending;
    let sendingNow = false;
    let composing = false;
    let reading = false;
    let recovering = false;
    const socket = typeof window.io === 'function' ? window.io('/chat', { auth: { csrf_token: csrf } }) : null;

    function nearBottom() {
        return messages.scrollHeight - messages.scrollTop - messages.clientHeight < 90;
    }

    function setStatus(text, state = 'saved') {
        status.textContent = text;
        status.dataset.state = state;
    }

    function updateComposer() {
        if (!textarea) return;
        const length = [...textarea.value].length;
        counter.textContent = `${length} / 2000`;
        counter.classList.toggle('is-near-limit', length >= 1800);
        button.disabled = sendingNow || !textarea.value.trim();
        form.setAttribute('aria-busy', String(sendingNow));
        buttonLabel.textContent = sendingNow ? 'Enviando…' : 'Enviar';
    }

    function updatePreview(message) {
        const row = document.querySelector(`[data-chat-list-id="${conversationId}"]`);
        if (!row) return;
        row.querySelector('[data-chat-preview]').textContent = message.body;
        let time = row.querySelector('[data-chat-list-time]');
        if (!time) {
            time = document.createElement('time');
            time.dataset.chatListTime = '';
            row.querySelector('.chat-conversation-top').append(time);
        }
        time.dateTime = message.created_at;
        const date = new Date(message.created_at);
        time.textContent = date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
        time.title = date.toLocaleString('pt-BR');
        row.parentElement.prepend(row);
    }

    function updateReadUI() {
        const row = document.querySelector(`[data-chat-list-id="${conversationId}"]`);
        let badge = row?.querySelector('[data-chat-row-unread]');
        const previous = Number(badge?.textContent || 0);
        const count = unseenUnread + unreadIds.size;
        if (count && row && !badge) {
            badge = document.createElement('span');
            badge.className = 'chat-count';
            badge.dataset.chatRowUnread = '';
            row.querySelector('.chat-conversation-bottom').append(badge);
        }
        if (badge) {
            if (count) {
                badge.textContent = count;
                badge.setAttribute('aria-label', `${count} mensagens não lidas`);
            } else badge.remove();
        }
        let total = document.querySelector('[data-chat-total-unread]');
        const all = Math.max(0, Number(total?.textContent || 0) + count - previous);
        if (all && !total) {
            total = document.createElement('span');
            total.className = 'chat-count';
            total.dataset.chatTotalUnread = '';
            document.querySelector('.chat-sidebar-heading').append(total);
        }
        if (total) {
            total.textContent = all;
            total.hidden = !all;
            total.setAttribute('aria-label', `${all} mensagens não lidas`);
        }
        if (readForm) readForm.hidden = latest <= lastRead;
        if (!count) newMessages.hidden = true;
    }

    function trackUnread(id) {
        if (unreadIds.has(id)) return;
        // Loaded history was already counted in the server's initial badge.
        if (id <= initialLatest && unseenUnread) unseenUnread--;
        unreadIds.add(id);
        updateReadUI();
    }

    function confirmRead(through) {
        for (const id of unreadIds) if (id <= through) unreadIds.delete(id);
        if (through >= initialLatest) unseenUnread = 0;
        // Reconcile confirmed IDs even if the reader moved away during the ACK.
        // Keep newer live IDs rather than trusting an older server count snapshot.
        updateReadUI();
    }

    async function http(path, body) {
        const response = await fetch(path, {
            method: body ? 'POST' : 'GET', credentials: 'same-origin',
            headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf } : {}) },
            ...(body ? { body: JSON.stringify(body) } : {}),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Não foi possível completar esta ação.');
        return result;
    }

    function event(name, payload) {
        return new Promise((resolve, reject) => {
            socket.timeout(7000).emit(name, { conversation_id: conversationId, ...payload }, (timeout, result) => {
                if (timeout) reject(new Error('A conexão caiu. Tentando recuperar o envio.'));
                else if (!result?.ok) reject(new Error(result?.error || 'Não foi possível completar esta ação.'));
                else resolve(result);
            });
        });
    }

    function showError(message = '') {
        if (!error) return;
        error.textContent = message;
        error.hidden = !message;
    }

    function render(message, animate = true, scrollOwn = false) {
        if (message.conversation_id !== conversationId) return;
        if (rendered.has(message.id)) {
            if (scrollOwn) messages.scrollTop = messages.scrollHeight;
            return;
        }
        const atBottom = nearBottom();
        const isLatest = message.id > latest;
        root.querySelector('[data-chat-empty]')?.remove();
        const row = document.createElement('li');
        row.className = 'chat-message';
        row.classList.toggle('is-own', message.sender?.id === userId);
        row.dataset.messageId = message.id;
        row.dataset.messageNonce = message.client_nonce;
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble';
        const author = document.createElement('strong');
        author.textContent = message.sender?.name || 'Conta excluída';
        const body = document.createElement('p');
        body.textContent = message.body;
        const date = document.createElement('time');
        date.dateTime = message.created_at;
        date.textContent = new Date(message.created_at).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
        bubble.append(author, body, date);
        row.append(bubble);
        const following = [...rendered].filter(([id]) => id > message.id).sort((a, b) => a[0] - b[0])[0]?.[1];
        messages.insertBefore(row, following || null);
        rendered.set(message.id, row);
        latest = Math.max(latest, message.id);
        if (isLatest) updatePreview(message);
        if (message.id > lastRead && message.sender?.id !== userId) trackUnread(message.id);
        if (readForm) readForm.elements.message_id.value = latest;
        if (animate) revealContent(row);
        if (atBottom || scrollOwn) messages.scrollTop = messages.scrollHeight;
        else if (message.id > lastRead && message.sender?.id !== userId) {
            newMessages.hidden = false;
            if (readForm) readForm.hidden = false;
        }
    }

    async function markRead() {
        if (!nearBottom() || !latest || document.visibilityState !== 'visible' || reading) return;
        if (latest <= lastRead) { updateReadUI(); return; }
        const through = latest;
        reading = true;
        let confirmed = false;
        try {
            if (socket?.connected) await event('mark_read', { message_id: through });
            else await http(endpoint + '/lida', { message_id: through });
            lastRead = Math.max(lastRead, through);
            confirmed = true;
            confirmRead(lastRead);
        } catch {
            if (readForm) readForm.hidden = false;
        } finally { reading = false; }
        // A newer message may arrive while this acknowledgement is outstanding.
        // Follow it only after a successful receipt and while the reader is at the end.
        if (confirmed && latest > lastRead) await markRead();
    }

    async function recover() {
        if (recovering) return;
        recovering = true;
        try {
            let cursor = latest || undefined;
            let more;
            do {
                const result = socket?.connected
                    ? await event('join', { after_id: cursor, limit: 100 })
                    : await http(endpoint + '/historico' + (cursor ? `?after_id=${cursor}&limit=100` : '?limit=100'));
                for (const message of result.messages) render(message, false);
                more = result.has_more && result.messages.length > 0;
                cursor = result.after_id;
            } while (more);
            setStatus(socket?.connected ? 'Conectado' : 'Histórico atualizado', socket?.connected ? 'connected' : 'saved');
            await markRead();
        } catch (failure) {
            setStatus(failure.message, 'error');
        } finally { recovering = false; }
    }

    socket?.on('connect', recover);
    socket?.on('disconnect', () => { setStatus('Reconectando… Suas mensagens estão salvas.', 'reconnecting'); });
    socket?.on('connect_error', () => { setStatus('Conexão indisponível. Você pode enviar pelo formulário.', 'error'); });
    socket?.on('message', ({ message }) => { render(message); markRead(); });
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') { recover(); markRead(); }
    });
    messages.addEventListener('scroll', () => { if (nearBottom()) markRead(); }, { passive: true });
    newMessages.addEventListener('click', async () => {
        messages.scrollTop = messages.scrollHeight;
        await markRead();
    });
    textarea?.addEventListener('input', () => { updateComposer(); showError(); });
    textarea?.addEventListener('compositionstart', () => { composing = true; });
    textarea?.addEventListener('compositionend', () => { composing = false; updateComposer(); });
    textarea?.addEventListener('keydown', event => {
        if (event.key !== 'Enter' || event.shiftKey || event.isComposing || composing || event.keyCode === 229) return;
        // A touch keyboard keeps Enter as a line break; its send button is explicit.
        if (document.documentElement.dataset.chatEnterSend === 'false' || matchMedia('(pointer: coarse)').matches) return;
        event.preventDefault();
        if (!sendingNow && textarea.value.trim()) form.requestSubmit();
    });
    if (form) form.querySelector('#chat-compose-help').textContent = document.documentElement.dataset.chatEnterSend === 'false' || matchMedia('(pointer: coarse)').matches
        ? 'Até 2000 caracteres · Toque em Enviar' : 'Enter envia · Shift + Enter pula linha';
    updateComposer();

    form?.addEventListener('submit', async (submit) => {
        submit.preventDefault();
        if (sendingNow) return;
        const body = textarea.value;
        if (!body.trim() || !form.reportValidity()) return;
        if (pending && pending.body !== body) form.elements.client_nonce.value = crypto.randomUUID();
        if (!pending || pending.body !== body) pending = { body, client_nonce: form.elements.client_nonce.value };
        const sending = pending;
        sendingNow = true;
        sendStatus.textContent = 'Enviando mensagem…';
        updateComposer();
        showError();
        try {
            let result;
            if (socket?.connected) {
                try { result = await event('send_message', sending); }
                catch { result = await http(form.action, sending); }
            } else result = await http(form.action, sending);
            render(result.message, true, true);
            if (textarea.value === sending.body) textarea.value = '';
            pending = null;
            form.elements.client_nonce.value = crypto.randomUUID();
            sendStatus.textContent = 'Mensagem enviada.';
            await markRead();
        } catch (failure) { showError(failure.message); sendStatus.textContent = 'Mensagem não enviada. Seu texto foi preservado.'; }
        finally { sendingNow = false; updateComposer(); textarea.focus({ preventScroll: true }); }
    });

    older?.addEventListener('click', async (click) => {
        click.preventDefault();
        const oldHeight = messages.scrollHeight;
        const oldTop = messages.scrollTop;
        const cursor = Math.min(...rendered.keys());
        try {
            const result = await http(endpoint + `/historico?before_id=${cursor}`);
            for (const message of result.messages) render(message, false);
            messages.scrollTop = oldTop + messages.scrollHeight - oldHeight;
            if (!result.has_more) older.hidden = true;
            else older.href = endpoint + `?before_id=${result.before_id}`;
        } catch (failure) { showError(failure.message); }
    });

    messages.scrollTop = messages.scrollHeight;
    for (const time of messages.querySelectorAll('time')) time.textContent = new Date(time.dateTime).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
    if (!socket) recover();
}
