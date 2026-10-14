import { setFieldError } from './controls.js';
import { cropImage } from './cropper.js';
import { revealContent } from '../motion.js';

/** Keep original images recoverable and release each temporary image URL. */
export function enhanceUploads() {
    document.querySelectorAll('input[data-preview]').forEach((input) => {
        const preview = document.getElementById(input.dataset.preview);
        if (!preview) return;
        const wrapper = input.closest('[data-upload]');
        const reset = wrapper?.querySelector('[data-upload-reset]');
        const crop = wrapper?.querySelector('[data-crop-image]');
        const status = wrapper?.querySelector('[data-upload-status]');
        const original = preview.getAttribute('src');
        const originalStatus = status?.textContent;
        preview.addEventListener('load', () => revealContent(preview));
        let objectUrl;
        let cropSource;
        let applyingCrop = false;
        let generation = 0;
        function restore() {
            if (objectUrl) URL.revokeObjectURL(objectUrl);
            objectUrl = undefined;
            preview.src = original;
            if (reset) reset.hidden = true;
            if (crop) crop.hidden = true;
            if (status) status.textContent = originalStatus;
        }
        input.addEventListener('change', () => {
            generation += 1;
            restore();
            input.setCustomValidity('');
            const file = input.files[0];
            if (!applyingCrop) cropSource = file;
            let message = '';
            if (file && (!/\.(png|jpe?g|gif)$/i.test(file.name) || (file.type && !['image/png', 'image/jpeg', 'image/gif'].includes(file.type)))) {
                message = 'Escolha uma imagem PNG, JPG ou GIF.';
            } else if (file?.size > 3 * 1024 * 1024) {
                message = 'A imagem deve ter até 3 MB. Escolha um arquivo menor.';
            }
            if (message) {
                // Keep the invalid selection visible and block submission until corrected.
                input.setCustomValidity(message);
                setFieldError(input, message);
                if (reset) reset.hidden = false;
                return;
            }
            setFieldError(input, '');
            if (!file) return;
            objectUrl = URL.createObjectURL(file);
            preview.src = objectUrl;
            if (status) status.textContent = 'Imagem selecionada. Confira a prévia antes de enviar.';
            if (reset) reset.hidden = false;
            if (crop) crop.hidden = false;
        });
        crop?.addEventListener('click', async () => {
            if (!cropSource) return;
            const version = generation;
            crop.disabled = true;
            try {
                const file = await cropImage(cropSource, {ratio:Number(wrapper.dataset.cropRatio), kind:wrapper.dataset.cropKind, trigger:crop});
                if (!file || generation !== version) return;
                const transfer = new DataTransfer();
                transfer.items.add(file);
                input.files = transfer.files;
                applyingCrop = true;
                input.dispatchEvent(new Event('change', {bubbles:true}));
                if (status) status.textContent = 'Recorte aplicado. Você pode ajustar novamente antes de enviar.';
            } catch (error) {
                setFieldError(input, error.message);
            } finally {
                applyingCrop = false;
                crop.disabled = false;
                if (!crop.hidden) crop.focus();
            }
        });
        reset?.addEventListener('click', () => {
            input.value = '';
            generation += 1;
            cropSource = undefined;
            input.setCustomValidity('');
            setFieldError(input, '');
            restore();
            input.dispatchEvent(new Event('change', {bubbles:true}));
            input.focus();
        });
        window.addEventListener('pagehide', (event) => {
            if (!event.persisted && objectUrl) URL.revokeObjectURL(objectUrl);
        });
    });
}
