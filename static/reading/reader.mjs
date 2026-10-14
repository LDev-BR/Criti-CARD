import { paginateText, pageForOffset } from './pagination.mjs';
import { revealContent } from '../motion.js';

/** A measured, keyboard-accessible reader shared by cards and the dialog. */
export class PaginatedReader {
    constructor(root) {
        this.root = root;
        this.viewport = root.querySelector('[data-reader-page]');
        this.previous = root.querySelector('[data-page-prev]');
        this.next = root.querySelector('[data-page-next]');
        this.counter = root.querySelector('[data-page-count]');
        this.pages = [''];
        this.index = 0;
        this.text = '';
        this.active = false;
        this.previous.addEventListener('click', () => this.go(-1));
        this.next.addEventListener('click', () => this.go(1));
        root.addEventListener('keydown', (event) => {
            if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                event.preventDefault();
                this.go(event.key === 'ArrowLeft' ? -1 : 1);
            }
        });
        this.observer = new ResizeObserver(() => this.scheduleLayout());
        this.observer.observe(this.viewport);
        document.fonts.ready.then(() => this.scheduleLayout());
    }

    get offset() { return this.pages.slice(0, this.index).join('').length; }

    open(text, offset = 0) {
        this.active = true;
        this.text = text;
        this.layout(offset);
    }

    close() { this.active = false; }

    scheduleLayout() {
        if (!this.active || this.frame) return;
        this.frame = requestAnimationFrame(() => {
            this.frame = null;
            if (this.active) this.layout(this.offset);
        });
    }

    layout(offset) {
        const width = this.viewport.clientWidth;
        const height = this.viewport.clientHeight;
        if (!width) return;
        // If a custom zoom/font leaves less than one line, offer scrollable text
        // instead of manufacturing thousands of unreadable one-character pages.
        this.scrollMode = height < parseFloat(getComputedStyle(this.viewport).lineHeight);
        this.viewport.classList.toggle('reader-scroll', this.scrollMode);
        if (this.scrollMode) {
            this.pages = [this.text];
            this.index = 0;
            this.render();
            return;
        }
        const measure = this.viewport.cloneNode(false);
        measure.removeAttribute('id');
        measure.removeAttribute('tabindex');
        measure.setAttribute('aria-hidden', 'true');
        // Keep the original font and whitespace rules while removing flex sizing.
        Object.assign(measure.style, {
            position: 'fixed', left: '-10000px', top: '0', visibility: 'hidden',
            width: `${width}px`, height: 'auto', minHeight: '0', maxHeight: 'none',
            flex: 'none', overflow: 'visible', margin: '0',
        });
        this.viewport.parentElement.append(measure);
        try {
            this.pages = paginateText(this.text, candidate => {
                measure.textContent = candidate;
                return measure.scrollHeight <= height;
            });
        } finally { measure.remove(); }
        this.index = pageForOffset(this.pages, offset);
        this.render();
    }

    go(direction) {
        const nextIndex = Math.max(0, Math.min(this.pages.length - 1, this.index + direction));
        if (nextIndex === this.index) return;
        this.index = nextIndex;
        this.render();
        revealContent(this.viewport);
    }

    render() {
        this.viewport.textContent = this.pages[this.index];
        this.counter.textContent = this.scrollMode ? 'Texto completo' : `Página ${this.index + 1} de ${this.pages.length}`;
        this.previous.disabled = this.index === 0;
        this.next.disabled = this.index === this.pages.length - 1;
    }
}
