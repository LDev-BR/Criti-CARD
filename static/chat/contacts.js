/** Name-based contact selection; native username forms remain usable without JS. */
export function enhanceContacts() {
    const form = document.querySelector('[data-chat-start]');
    if (!form) return;
    const input = form.querySelector('[data-chat-contact-input]');
    const target = form.querySelector('[data-chat-contact-id]');
    const results = form.querySelector('[data-chat-contact-results]');
    const status = form.querySelector('[data-chat-contact-status]');
    const panel = form.closest('[data-chat-start-panel]');
    let controller, timer, requestId = 0, selected = -1, people = [];
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-controls', results.id);
    input.setAttribute('aria-expanded', 'false');
    form.querySelector('#chat-contact-help').textContent = 'Busque pelo nome ou @usuário e escolha uma pessoa.';

    function close() {
        requestId++;
        clearTimeout(timer);
        controller?.abort();
        results.hidden = true;
        input.setAttribute('aria-expanded', 'false');
        input.removeAttribute('aria-activedescendant');
        input.removeAttribute('aria-busy');
        selected = -1;
    }

    function message(text = '') {
        status.textContent = text;
        status.hidden = !text;
    }

    function choose(index) {
        const person = people[index];
        if (!person) return;
        input.value = '@' + person.username;
        target.value = person.id;
        target.disabled = false;
        close();
        message(`${person.nome} selecionado. Clique em Conversar para começar.`);
        input.focus({ preventScroll: true });
    }

    function activate(index) {
        const nodes = [...results.children];
        if (!nodes.length) return;
        selected = (index + nodes.length) % nodes.length;
        nodes.forEach((node, position) => node.setAttribute('aria-selected', String(position === selected)));
        input.setAttribute('aria-activedescendant', nodes[selected].id);
        nodes[selected].scrollIntoView({ block: 'nearest' });
    }

    function avatarURL(value) {
        try {
            const url = new URL(value, location.origin);
            if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) return url.href;
        } catch { /* The public fallback works for an absent or invalid image. */ }
        return '/static/default-avatar.svg';
    }

    async function search(query, sequence) {
        controller = new AbortController();
        input.setAttribute('aria-busy', 'true');
        message('Buscando pessoas…');
        try {
            const response = await fetch('/conexoes?' + new URLSearchParams({ aba: 'descobrir', q: query }), {
                headers: { Accept: 'application/json' }, credentials: 'same-origin', signal: controller.signal,
            });
            if (!response.ok) throw new Error('Busca indisponível. Tente novamente ou use o @usuário completo.');
            const data = await response.json();
            if (sequence !== requestId) return;
            people = data.people || [];
            results.replaceChildren();
            selected = -1;
            for (const [index, person] of people.entries()) {
                const option = document.createElement('li');
                option.id = 'chat-contact-' + person.id;
                option.setAttribute('role', 'option');
                option.setAttribute('aria-selected', 'false');
                option.setAttribute('aria-label', `${person.nome} @${person.username}`);
                const avatar = document.createElement('img');
                avatar.className = 'chat-avatar';
                avatar.src = avatarURL(person.avatar_url);
                avatar.alt = '';
                avatar.width = avatar.height = 32;
                const copy = document.createElement('div');
                const name = document.createElement('strong');
                name.textContent = person.nome;
                const username = document.createElement('small');
                username.textContent = '@' + person.username;
                copy.append(name, username);
                option.append(avatar, copy);
                option.addEventListener('pointerdown', event => event.preventDefault());
                option.addEventListener('click', () => choose(index));
                results.append(option);
            }
            results.hidden = !people.length;
            input.setAttribute('aria-expanded', String(!!people.length));
            message(people.length ? `${people.length} ${people.length === 1 ? 'pessoa encontrada' : 'pessoas encontradas'}. Use as setas para escolher.` : 'Nenhuma pessoa encontrada. Tente outro nome.');
        } catch (failure) {
            if (sequence !== requestId || failure.name === 'AbortError') return;
            results.hidden = true;
            message(failure.message);
        } finally {
            if (sequence === requestId) input.removeAttribute('aria-busy');
        }
    }

    input.addEventListener('input', () => {
        close();
        target.disabled = true;
        target.value = '';
        message();
        const query = input.value.trim();
        if (query.length < 2) return;
        const sequence = requestId;
        timer = setTimeout(() => search(query, sequence), 220);
    });
    input.addEventListener('keydown', event => {
        if (event.key === 'Escape') { close(); message(); return; }
        if (results.hidden) return;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            activate(selected < 0 ? (event.key === 'ArrowDown' ? 0 : people.length - 1)
                : selected + (event.key === 'ArrowDown' ? 1 : -1));
        } else if (event.key === 'Enter' && selected >= 0) {
            event.preventDefault();
            choose(selected);
        } else if (event.key === 'Tab') close();
    });
    input.addEventListener('blur', close);
    panel.addEventListener('toggle', () => { if (!panel.open) close(); });
    document.addEventListener('pointerdown', event => { if (!form.contains(event.target)) close(); });
    document.querySelectorAll('[data-chat-new]').forEach(button => {
        button.hidden = false;
        button.addEventListener('click', () => { panel.open = true; input.focus(); });
    });
}

export function enhanceConversationList() {
    const input = document.querySelector('[data-chat-filter]');
    const rows = [...document.querySelectorAll('[data-chat-list-item]')];
    if (!input || !rows.length) return;
    document.querySelector('[data-chat-filter-wrap]').hidden = false;
    const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
    input.addEventListener('input', () => {
        const query = normalize(input.value.trim());
        let count = 0;
        for (const row of rows) {
            row.hidden = !normalize(row.dataset.chatSearch).includes(query);
            if (!row.hidden) count++;
        }
        document.querySelector('[data-chat-filter-empty]').hidden = !!count;
    });
    for (const time of document.querySelectorAll('[data-chat-list-time]')) {
        const date = new Date(time.dateTime);
        time.textContent = date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
        time.title = date.toLocaleString('pt-BR');
    }
}
