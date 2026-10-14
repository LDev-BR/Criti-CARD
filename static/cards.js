import { PaginatedReader } from './reading/reader.mjs';

const dialog = document.getElementById('review-dialog');
const expandedReader = dialog ? new PaginatedReader(dialog.querySelector('[data-reader]')) : null;

if (dialog) {
    dialog.querySelector('[data-close-dialog]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', (event) => {
        const bounds = dialog.getBoundingClientRect();
        if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right
            || event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close();
    });
    dialog.addEventListener('close', () => {
        expandedReader.close();
        document.body.classList.remove('dialog-open');
    });
}

class ReviewCard {
    constructor(card) {
        this.card = card;
        this.surface = card.querySelector('.card-surface');
        this.front = card.querySelector('[data-card-front]');
        this.back = card.querySelector('[data-card-back]');
        this.closeButton = card.querySelector('[data-close-preview]');
        this.reader = new PaginatedReader(card.querySelector('[data-reader]'));
        this.text = card.querySelector('[data-review-text]').content.textContent;
        this.pinned = false;
        this.blockHover = false;
        card.querySelectorAll('[data-open-review]').forEach(link => {
            link.addEventListener('click', (event) => {
                event.preventDefault();
                this.open(true);
            });
        });
        this.surface.addEventListener('click', (event) => {
            if (!event.target.closest('a,button,input,form')) this.open(true);
        });
        this.surface.addEventListener('pointerenter', (event) => {
            if (document.documentElement.dataset.cardHover === 'false' || event.pointerType === 'touch' || this.blockHover || this.pinned
                || !window.matchMedia('(hover: hover) and (pointer: fine)').matches
                || this.front.contains(document.activeElement)) return;
            clearTimeout(this.leaveTimer);
            this.hoverTimer = setTimeout(() => {
                if (!this.pinned && !this.blockHover && !this.front.contains(document.activeElement)) this.open(false);
            }, 280);
        });
        this.front.addEventListener('focusin', () => clearTimeout(this.hoverTimer));
        this.surface.addEventListener('pointerleave', () => {
            clearTimeout(this.hoverTimer);
            this.blockHover = false;
            if (!this.pinned) this.leaveTimer = setTimeout(() => this.close(), 180);
        });
        this.closeButton.addEventListener('click', () => {
            this.blockHover = true;
            this.close(true);
        });
        this.back.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') { this.blockHover = true; this.close(true); }
        });
        this.back.addEventListener('focusin', () => { this.pinned = true; });
        card.querySelector('[data-expand-review]').addEventListener('click', () => this.expand());
    }

    open(pinned) {
        clearTimeout(this.hoverTimer);
        clearTimeout(this.leaveTimer);
        this.pinned = this.pinned || pinned;
        if (this.back.hidden) {
            this.front.hidden = true;
            this.front.inert = true;
            this.back.hidden = false;
            this.card.classList.add('is-reading');
            this.reader.open(this.text);
        }
        if (pinned) this.closeButton.focus({ preventScroll: true });
    }

    close(restoreFocus = false) {
        clearTimeout(this.hoverTimer);
        clearTimeout(this.leaveTimer);
        this.reader.close();
        this.pinned = false;
        this.back.hidden = true;
        this.front.hidden = false;
        this.front.inert = false;
        this.card.classList.remove('is-reading');
        if (restoreFocus) this.front.querySelector('.read-review').focus({ preventScroll: true });
    }

    expand() {
        if (!dialog) return;
        this.pinned = true;
        dialog.querySelector('[data-dialog-title]').textContent = this.card.dataset.title;
        dialog.querySelector('[data-dialog-title]').title = this.card.dataset.title;
        dialog.querySelector('[data-dialog-author]').textContent = this.card.dataset.author;
        dialog.querySelector('[data-dialog-score]').textContent = this.card.dataset.score;
        const cover = dialog.querySelector('[data-dialog-cover]');
        const source = this.card.querySelector('.card-cover');
        const sourceImage = source.querySelector('img') || source;
        cover.src = sourceImage.src;
        cover.alt = sourceImage.alt;
        const dialogArt = dialog.querySelector('[data-dialog-art]');
        const previousFrame = dialogArt.querySelector('.catalog-art-frame');
        if (previousFrame) previousFrame.replaceWith(cover);
        dialogArt.className = 'dialog-cover catalog-art';
        for (const name of source.classList) {
            if (name.startsWith('catalog-art--')) dialogArt.classList.add(name);
        }
        if (dialogArt.classList.contains('catalog-art--atlas')) {
            const frame = document.createElement('span');
            frame.className = 'catalog-art-frame';
            cover.replaceWith(frame);
            frame.append(cover);
        }
        document.body.classList.add('dialog-open');
        dialog.showModal();
        expandedReader.open(this.text, this.reader.offset);
        dialog.querySelector('[data-close-dialog]').focus({ preventScroll: true });
    }
}

const enhancedCards = new WeakMap();
function enhanceCards(scope) {
    scope.querySelectorAll('[data-review-card]').forEach(card => {
        if (enhancedCards.has(card)) return;
        enhancedCards.set(card, new ReviewCard(card));
    });
}
enhanceCards(document);
document.addEventListener('criticard:results-updated', event => enhanceCards(event.target));
document.addEventListener('criticard:results-removing', event => {
    event.target.querySelectorAll('[data-review-card]').forEach(card => {
        const review = enhancedCards.get(card);
        if (!review) return;
        clearTimeout(review.hoverTimer);
        clearTimeout(review.leaveTimer);
        review.reader.close();
        review.reader.observer.disconnect();
        cancelAnimationFrame(review.reader.frame);
    });
});
