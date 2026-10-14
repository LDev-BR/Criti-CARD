/** Catalogue preview is temporary and stays within this form. */
document.querySelectorAll('[data-admin-work-editor]').forEach((editor) => {
    const title = editor.querySelector('[name=titulo]');
    const category = editor.querySelector('[name=categoria_id]');
    const input = editor.querySelector('[name=capa]');
    const image = editor.querySelector('#cover-preview');
    const artwork = image.closest('.catalog-art');
    const originalClasses = artwork.className;
    const originalArt = artwork.classList.contains('catalog-art--atlas');
    const updateText = () => {
        editor.querySelector('[data-admin-preview-title]').textContent = title.value.trim() || 'O título da obra';
        editor.querySelector('[data-admin-preview-category]').textContent = category.value ? category.selectedOptions[0].textContent : 'Escolha uma categoria';
    };
    const updateImage = () => {
        const frame = artwork.querySelector('.catalog-art-frame');
        if (frame) frame.replaceWith(image);
        artwork.className = input.files.length && image.getAttribute('src').startsWith('blob:') ? 'catalog-art' : originalClasses;
        if (artwork.classList.contains('catalog-art--atlas') && originalArt) {
            const restoredFrame = document.createElement('span');
            restoredFrame.className = 'catalog-art-frame';
            image.replaceWith(restoredFrame);
            restoredFrame.append(image);
        }
    };
    title.addEventListener('input', updateText);
    category.addEventListener('change', updateText);
    input.addEventListener('change', updateImage);
    updateText();
});
