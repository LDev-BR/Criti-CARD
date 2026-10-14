import { cropRectangle } from './crop-geometry.mjs';

const dialog = document.getElementById('crop-dialog');
const canvas = dialog.querySelector('[data-crop-canvas]');
const zoom = dialog.querySelector('#crop-zoom');
const horizontal = dialog.querySelector('#crop-x');
const vertical = dialog.querySelector('#crop-y');
const apply = dialog.querySelector('[data-crop-apply]');
const error = dialog.querySelector('[data-crop-error]');
let current;
let drag;

function rectangle() {
    return cropRectangle(current.image.naturalWidth, current.image.naturalHeight, current.ratio,
        Number(zoom.value), Number(horizontal.value) / 100, Number(vertical.value) / 100);
}

function draw() {
    if (!current) return;
    const crop = rectangle();
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(current.image, crop.x, crop.y, crop.width, crop.height, 0, 0, canvas.width, canvas.height);
    dialog.querySelector('[data-crop-zoom-label]').textContent = `${Math.round(Number(zoom.value) * 100)}%`;
}

function finish(value) {
    if (!current) return;
    const state = current;
    current = undefined;
    drag = undefined;
    dialog.close();
    URL.revokeObjectURL(state.url);
    state.resolve(value);
}

export async function cropImage(file, {ratio, kind, trigger}) {
    if (current) return null;
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.src = url;
    try {
        await image.decode();
        if (image.naturalWidth * image.naturalHeight > 16_000_000) throw new Error('A imagem deve ter até 16 megapixels.');
    } catch (cause) {
        URL.revokeObjectURL(url);
        throw new Error(cause.message?.includes('megapixels') ? cause.message : 'Não foi possível abrir a imagem. Escolha outro arquivo.');
    }
    return new Promise((resolve) => {
        current = {image, file, ratio, trigger, resolve, url, kind};
        canvas.width = kind === 'avatar' ? 768 : 1050;
        canvas.height = Math.round(canvas.width / ratio);
        dialog.classList.toggle('avatar-crop', kind === 'avatar');
        dialog.querySelector('#crop-heading').textContent = kind === 'avatar' ? 'Recorte sua foto de perfil' : 'Enquadre a capa do card';
        zoom.value = '1'; horizontal.value = vertical.value = '50';
        error.hidden = true;
        apply.disabled = false;
        dialog.showModal();
        draw();
        zoom.focus();
    });
}

[zoom, horizontal, vertical].forEach((input) => input.addEventListener('input', draw));
dialog.querySelectorAll('[data-crop-cancel]').forEach((button) => button.addEventListener('click', () => finish(null)));
dialog.addEventListener('cancel', (event) => { event.preventDefault(); finish(null); });
dialog.addEventListener('close', () => { if (current) finish(null); });
canvas.addEventListener('pointerdown', (event) => {
    if (!current) return;
    drag = {id: event.pointerId, x: event.clientX, y: event.clientY, crop: rectangle()};
    canvas.setPointerCapture(event.pointerId);
});
canvas.addEventListener('pointermove', (event) => {
    if (!drag || event.pointerId !== drag.id || !current) return;
    const rect = canvas.getBoundingClientRect();
    const x = drag.crop.x - (event.clientX - drag.x) / rect.width * drag.crop.width;
    const y = drag.crop.y - (event.clientY - drag.y) / rect.height * drag.crop.height;
    const xSpace = current.image.naturalWidth - drag.crop.width;
    const ySpace = current.image.naturalHeight - drag.crop.height;
    horizontal.value = String(xSpace > 0 ? Math.max(0, Math.min(100, x / xSpace * 100)) : 50);
    vertical.value = String(ySpace > 0 ? Math.max(0, Math.min(100, y / ySpace * 100)) : 50);
    draw();
});
const endDrag = () => { drag = undefined; };
canvas.addEventListener('pointerup', endDrag);
canvas.addEventListener('pointercancel', endDrag);
canvas.addEventListener('lostpointercapture', endDrag);

apply.addEventListener('click', () => {
    if (!current || apply.disabled) return;
    const state = current;
    apply.disabled = true;
    const type = state.file.type === 'image/jpeg' ? 'image/jpeg' : 'image/png';
    canvas.toBlob((blob) => {
        if (current !== state) return;
        if (!blob || blob.size > 3 * 1024 * 1024) {
            error.textContent = 'Não foi possível gerar o recorte. Tente outra imagem.';
            error.hidden = false;
            apply.disabled = false;
            return;
        }
        const name = state.file.name.replace(/\.[^.]*$/, '') + '-recorte.' + (type === 'image/jpeg' ? 'jpg' : 'png');
        finish(new File([blob], name, {type}));
    }, type, 0.92);
});
