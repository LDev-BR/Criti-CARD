/** Personal preferences: native writes, reversible appearance preview and clear feedback. */
const root = document.documentElement;
const form = document.querySelector('[data-settings-form]');
const attributes = { color_scheme: 'theme', text_size: 'textSize', reduce_motion: 'reduceMotion',
    high_contrast: 'highContrast', card_hover: 'cardHover', card_density: 'cardDensity', card_excerpt: 'cardExcerpt' };
let dirty = false;

if (form) {
    const status = form.querySelector('[data-settings-dirty]');
    const save = form.querySelector('[data-settings-save]');
    const discard = form.querySelector('[data-settings-discard]');
    const snapshot = () => JSON.stringify([...new FormData(form)].filter(([name]) => name !== 'csrf_token'));
    const original = snapshot();
    const originalAttributes = Object.fromEntries(Object.values(attributes).map(name => [name, root.dataset[name]]));
    function preview() {
        if (form.dataset.settingsSection !== 'aparencia') return;
        for (const [name, attribute] of Object.entries(attributes)) {
            const control = form.elements.namedItem(name);
            if (control) root.dataset[attribute] = control.type === 'checkbox' ? String(control.checked) : control.value;
        }
    }
    function refresh() {
        dirty = snapshot() !== original;
        status.dataset.dirty = String(dirty);
        status.querySelector('span').textContent = dirty ? 'Você tem alterações para salvar' : 'Preferências salvas na sua conta';
        save.disabled = !dirty;
        discard.hidden = !dirty;
        preview();
    }
    form.addEventListener('input', refresh);
    form.addEventListener('change', refresh);
    discard.addEventListener('click', () => {
        form.reset();
        for (const [attribute, value] of Object.entries(originalAttributes)) root.dataset[attribute] = value;
        refresh();
        form.querySelector('input:not([type=hidden]), select')?.focus();
    });
    form.addEventListener('submit', () => {
        dirty = false;
        status.querySelector('span').textContent = 'Salvando suas preferências…';
        save.disabled = true;
    });
    window.addEventListener('beforeunload', event => {
        if (!dirty) return;
        event.preventDefault();
        event.returnValue = '';
    });
    save.disabled = true;
}

const search = document.querySelector('#settings-search');
if (search) {
    document.querySelector('[data-settings-search-wrap]').hidden = false;
    const links = [...document.querySelectorAll('[data-settings-area]')];
    const result = document.querySelector('[data-settings-search-status]');
    const simplify = text => text.normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase('pt-BR');
    search.addEventListener('input', () => {
        const query = simplify(search.value.trim());
        for (const link of links) link.hidden = !simplify(link.dataset.settingsSearch).includes(query);
        const count = links.filter(link => !link.hidden).length;
        if (query && count) search.closest('[data-responsive-disclosure]')?.setAttribute('open', '');
        result.hidden = !query;
        result.textContent = count ? `${count} ${count === 1 ? 'área encontrada' : 'áreas encontradas'}` : 'Nenhuma área encontrada. Tente outra palavra.';
    });
    search.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
            event.preventDefault();
            const first = links.find(link => !link.hidden);
            if (first) first.click();
        }
    });
}
