/** Shared, progressively enhanced controls. Server validation remains authoritative. */
import { passwordChecks } from './password-policy.mjs';

export function setFieldError(input, message) {
    const error = input.form?.querySelector(`[data-field-error="${CSS.escape(input.name)}"]`);
    input.setAttribute('aria-invalid', message ? 'true' : 'false');
    if (error) {
        error.textContent = message;
        error.hidden = !message;
    }
}

function fieldMessage(input) {
    const validity = input.validity;
    if (validity.customError) return input.validationMessage;
    if (validity.badInput) return 'Informe uma nota inteira de 0 a 100.';
    if (validity.valueMissing || (input.required && input.type !== 'file' && input.name !== 'senha' && !input.value.trim())) {
        return input.type === 'file' ? 'Escolha uma imagem de capa.' : 'Preencha este campo.';
    }
    if (validity.typeMismatch) return 'Informe um email válido, como voce@exemplo.com.';
    if (validity.patternMismatch) return 'Use de 3 a 15 letras, números, hífen ou sublinhado.';
    if (validity.rangeUnderflow || validity.rangeOverflow || validity.stepMismatch) return 'Informe uma nota inteira de 0 a 100.';
    if (validity.tooShort) return `Use pelo menos ${input.minLength} caracteres.`;
    if (validity.tooLong) return `Use até ${input.maxLength} caracteres.`;
    return '';
}

export function enhanceForms() {
    document.querySelectorAll('form[data-validate]').forEach((form) => {
        const inputs = Array.from(form.elements).filter((input) => input.matches('input:not([type=hidden]), textarea, select') && !input.readOnly);
        const status = form.querySelector('[data-form-status]');
        const submit = form.querySelector('[type=submit]');
        form.noValidate = true;
        for (const input of inputs) {
            input.addEventListener('blur', () => setFieldError(input, fieldMessage(input)));
            input.addEventListener('input', () => {
                if (input.getAttribute('aria-invalid') === 'true') setFieldError(input, fieldMessage(input));
                if (status) status.hidden = true;
            });
        }
        form.addEventListener('submit', (event) => {
            const invalid = inputs.filter((input) => {
                const message = fieldMessage(input);
                setFieldError(input, message);
                return !!message;
            });
            if (invalid.length) {
                event.preventDefault();
                if (status) {
                    status.textContent = 'Revise os campos indicados. Você pode continuar de onde parou.';
                    status.hidden = false;
                }
                // Reveal optional sections before focusing their invalid control.
                for (let section = invalid[0].closest('details'); section; section = section.parentElement?.closest('details')) {
                    section.open = true;
                }
                invalid[0].focus();
                return;
            }
            if (submit) {
                submit.disabled = true;
                submit.dataset.originalLabel = submit.innerHTML;
                submit.textContent = 'Enviando…';
            }
        });
        window.addEventListener('pageshow', () => {
            if (submit?.dataset.originalLabel) {
                submit.innerHTML = submit.dataset.originalLabel;
                submit.disabled = false;
            }
        });
        form.querySelector('[aria-invalid=true]')?.focus();
    });
}

export function enhancePasswords() {
    document.querySelectorAll('[data-password-toggle]').forEach((button) => {
        const input = document.getElementById(button.dataset.passwordToggle);
        if (!input) return;
        button.hidden = false;
        const setVisibility = (reveal) => {
            input.type = reveal ? 'text' : 'password';
            button.querySelector('[data-password-label]').textContent = reveal ? 'Ocultar' : 'Mostrar';
            button.querySelector('[data-show-password-icon]').hidden = reveal;
            button.querySelector('[data-hide-password-icon]').hidden = !reveal;
            button.setAttribute('aria-label', reveal ? 'Ocultar senha' : 'Mostrar senha');
            button.setAttribute('aria-pressed', String(reveal));
        };
        button.addEventListener('click', () => setVisibility(input.type === 'password'));
        window.addEventListener('pagehide', () => setVisibility(false));
        const caps = input.closest('.field').querySelector('[data-caps-lock]');
        const updateCaps = (event) => {
            if (caps && event.getModifierState) caps.hidden = !event.getModifierState('CapsLock');
        };
        input.addEventListener('keydown', updateCaps);
        input.addEventListener('keyup', updateCaps);
        input.addEventListener('blur', () => { if (caps) caps.hidden = true; });
        if (input.hasAttribute('data-password-rules')) {
            const checklist = input.closest('.field').querySelector('[data-password-checklist]');
            const update = () => {
                const checks = passwordChecks(input.value);
                input.setCustomValidity(input.value && !Object.values(checks).every(Boolean) ? 'Complete os requisitos da senha indicados abaixo.' : '');
                for (const item of checklist.querySelectorAll('[data-rule]')) {
                    item.dataset.met = String(checks[item.dataset.rule]);
                }
            };
            input.addEventListener('input', update);
            update();
        }
    });
}

export function enhanceCounters() {
    document.querySelectorAll('[data-counter]').forEach((input) => {
        const counter = document.getElementById(input.dataset.counter);
        if (!counter) return;
        const update = () => {
            counter.textContent = `${input.value.length}/${input.maxLength}`;
            counter.classList.toggle('at-limit', input.value.length >= input.maxLength);
        };
        input.addEventListener('input', update);
        update();
    });
}
