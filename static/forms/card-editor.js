/** A display-only preview: it never submits or persists a personal draft. */
export function enhanceCardEditor() {
    document.querySelectorAll('[data-card-editor]').forEach((editor) => {
        const title = editor.querySelector('[name=titulo]');
        const description = editor.querySelector('[name=sobre]');
        const score = editor.querySelector('[name=nota]');
        const category = editor.querySelector('[name=categoria_id]');
        const work = editor.querySelector('[name=obra_id]');
        if (!title || !description || !score || !category || !work) return;
        editor.querySelector('[data-live-indicator]')?.removeAttribute('hidden');
        const search = editor.querySelector('[data-work-search]');
        const clearSearch = editor.querySelector('[data-clear-work-search]');
        editor.querySelector('[data-work-search-wrap]')?.removeAttribute('hidden');
        const searchStatus = editor.querySelector('[data-work-search-status]');
        const existingNotice = editor.querySelector('[data-existing-review]');
        const existingMessage = existingNotice?.querySelector('[data-existing-message]');
        const existingEdit = existingNotice?.querySelector('[data-existing-edit]');
        const submit = editor.querySelector('[type=submit]');
        const legacyField = editor.querySelector('[data-legacy-title-field]');
        const cover = editor.querySelector('#cover-preview');
        const coverFrame = editor.querySelector('[data-draft-cover]');
        const selectedCover = editor.querySelector('[data-selected-cover-image]');
        const selectedCoverFrame = editor.querySelector('[data-selected-cover]');
        const originalCover = cover?.getAttribute('src');
        const placeholderCover = new URL('../default-cover.svg', import.meta.url).href;
        const normalize = (value) => value.normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase('pt-BR');
        const groups = Array.from(work.querySelectorAll('optgroup')).map((group) => group.cloneNode(true));
        let legacyTitle = title.value;
        const filterWorks = () => {
            const selected = work.value;
            work.querySelectorAll('optgroup').forEach((group) => group.remove());
            const query = normalize(search?.value.trim() || '');
            groups.filter((group) => !category.value || group.dataset.category === category.value)
                .forEach((group) => {
                    const filtered = group.cloneNode(true);
                    filtered.querySelectorAll('option').forEach((option) => {
                        if (query && !normalize(option.textContent).includes(query) && option.value !== selected) option.remove();
                    });
                    if (filtered.children.length) work.append(filtered);
                });
            work.value = Array.from(work.options).some((option) => option.value === selected) ? selected : '';
            const count = work.options.length - 1;
            if (searchStatus) searchStatus.textContent = count
                ? `${count} ${count === 1 ? 'obra disponível' : 'obras disponíveis'}.`
                : 'Nenhuma obra encontrada. Tente outro título ou categoria.';
            if (clearSearch) clearSearch.hidden = !search?.value;
        };
        const renderCover = (frame, image, selected) => {
            if (!frame || !image) return;
            frame.querySelector('.catalog-art-frame')?.replaceWith(image);
            for (const name of Array.from(frame.classList)) {
                if (name.startsWith('catalog-art--')) frame.classList.remove(name);
            }
            if (work.value && selected?.dataset.artSource) {
                image.src = selected.dataset.artSource;
                if (image === cover) image.alt = `Capa do catálogo de ${selected.dataset.title || selected.textContent}`;
                frame.classList.add('catalog-art--atlas',
                    `catalog-art--col-${selected.dataset.artColumn}`, `catalog-art--row-${selected.dataset.artRow}`);
                const atlas = document.createElement('span');
                atlas.className = 'catalog-art-frame';
                image.replaceWith(atlas);
                atlas.append(image);
            } else {
                image.src = work.value ? (selected?.dataset.coverSource || placeholderCover)
                    : (legacyField ? originalCover : placeholderCover);
                if (image === cover) image.alt = work.value ? `Capa de ${selected.dataset.title || selected.textContent}` : 'Prévia da capa';
            }
        };
        const updateCover = () => {
            const selected = work.selectedOptions[0];
            renderCover(coverFrame, cover, selected);
            renderCover(selectedCoverFrame, selectedCover, selected);
        };
        const update = () => {
            const selected = work.value ? work.selectedOptions[0] : null;
            const selectedTitle = selected?.dataset.title || selected?.textContent || title.value.trim();
            editor.querySelector('[data-draft-title]').textContent = selectedTitle || 'O título da sua obra';
            editor.querySelector('[data-draft-excerpt]').textContent = description.value.trim() || 'As primeiras linhas da sua crítica aparecem aqui. Sua experiência dá vida ao card.';
            const value = Number(score.value);
            editor.querySelector('[data-draft-score]').textContent = score.value !== '' && Number.isInteger(value) && value >= 0 && value <= 100 ? value : '—';
            editor.querySelector('[data-draft-category]').textContent = selected?.dataset.categoryName || 'CRITI-CARD';
            const summary = editor.querySelector('[data-selected-work]');
            if (summary) {
                summary.dataset.empty = String(!selected && !legacyField);
                summary.querySelector('[data-selected-title]').textContent = selectedTitle || 'Escolha uma obra para começar';
                summary.querySelector('[data-selected-category]').textContent = selected?.dataset.categoryName || (legacyField ? 'CARD ANTERIOR' : 'SEU PRÓXIMO CARD');
                summary.querySelector('[data-selected-note]').textContent = selected
                    ? (selected.dataset.retired === 'true' ? 'Obra retirada · sua crítica pode ser editada.' : 'Capa do catálogo · pronta para o seu card')
                    : (legacyField ? 'Sua capa anterior será preservada.' : 'A capa do catálogo aparece aqui.');
            }
        };
        const selectWork = () => {
            title.value = work.value ? (work.selectedOptions[0].dataset.title || work.selectedOptions[0].textContent) : (work.required ? '' : legacyTitle);
            const selected = work.value ? work.selectedOptions[0] : null;
            const hasReview = !!selected?.dataset.existingCard;
            work.setCustomValidity(hasReview ? 'Você já avaliou esta obra. Edite seu card existente.' : '');
            if (existingNotice) existingNotice.hidden = !hasReview;
            if (existingMessage) existingMessage.textContent = hasReview
                ? `Você já avaliou ${selected.dataset.title || selected.textContent}. Atualize seu card existente.` : '';
            if (existingEdit) {
                if (hasReview && selected.dataset.editUrl) existingEdit.href = selected.dataset.editUrl;
                else existingEdit.removeAttribute('href');
            }
            if (submit) {
                submit.disabled = hasReview;
                if (hasReview) submit.setAttribute('aria-describedby', 'existing-review-notice');
                else submit.removeAttribute('aria-describedby');
            }
            title.readOnly = !!work.value || work.required;
            if (legacyField) {
                legacyField.hidden = !!work.value;
                title.required = !work.value;
            }
            work.dispatchEvent(new Event('input', {bubbles:true}));
            update();
            updateCover();
        };
        category.addEventListener('change', () => { if (search) search.value = ''; filterWorks(); selectWork(); });
        search?.addEventListener('input', filterWorks);
        clearSearch?.addEventListener('click', () => { search.value = ''; filterWorks(); search.focus(); });
        work.addEventListener('change', selectWork);
        filterWorks();
        selectWork();
        title.addEventListener('input', () => { if (!work.value) legacyTitle = title.value; });
        [title, description, score].forEach((input) => input.addEventListener('input', update));
        enhanceScoreSlider(editor, score);
        update();
        enhanceMobilePreview(editor);
    });
}

function enhanceScoreSlider(editor, score) {
    const slider = editor.querySelector('[data-score-slider]');
    if (!slider) return;
    editor.querySelector('[data-score-slider-wrap]')?.removeAttribute('hidden');
    slider.addEventListener('input', () => {
        score.value = slider.value;
        score.dispatchEvent(new Event('input', {bubbles:true}));
    });
    const sync = () => {
        if (score.value !== '' && score.validity.valid) slider.value = score.value;
        slider.setAttribute('aria-valuetext', score.value !== '' && score.validity.valid ? `${score.value} de 100` : 'Escolha uma nota de 0 a 100');
    };
    score.addEventListener('input', sync);
    sync();
}

function enhanceMobilePreview(editor) {
    const composer = editor.closest('.composer');
    const trigger = composer?.querySelector('[data-open-draft]');
    const preview = editor.querySelector('.editor-preview');
    const close = preview?.querySelector('[data-close-draft]');
    if (!trigger || !preview || !close || !('HTMLDialogElement' in window)) return;
    const media = window.matchMedia('(max-width:850px)');
    const dialog = document.createElement('dialog');
    dialog.className = 'draft-preview-dialog';
    dialog.setAttribute('aria-label', 'Prévia do seu card');
    editor.append(dialog);
    composer.dataset.mobilePreview = 'true';
    let placeholder;
    trigger.hidden = false;
    trigger.addEventListener('click', () => {
        if (dialog.open || !media.matches) return;
        placeholder = document.createComment('draft-preview-location');
        preview.before(placeholder);
        dialog.append(preview);
        close.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
        dialog.showModal();
        close.focus();
    });
    close.addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => {
        const focused = document.activeElement;
        const restoreFocus = !focused || focused === document.body || focused === trigger || dialog.contains(focused);
        placeholder?.replaceWith(preview);
        close.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
        // Native restoration happens before this asynchronous event. Preserve
        // a newer action, such as returning to the critique field to type.
        if (restoreFocus) {
            if (trigger.getClientRects().length) trigger.focus();
            else editor.querySelector('[name=obra_id]')?.focus();
        }
    });
    media.addEventListener('change', () => { if (!media.matches && dialog.open) dialog.close(); });
}
