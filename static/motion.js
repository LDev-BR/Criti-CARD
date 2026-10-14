/** Brief feedback for changing content, honoring live accessibility preferences. */
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const active = new Map();

function reduceMotion() {
    return reducedMotion.matches || document.documentElement.dataset.reduceMotion === 'true';
}
function cancelReducedMotion() {
    if (reduceMotion()) {
        for (const animation of active.values()) animation.cancel();
        active.clear();
    }
}
reducedMotion.addEventListener('change', cancelReducedMotion);
new MutationObserver(cancelReducedMotion).observe(document.documentElement, {
    attributes: true, attributeFilter: ['data-reduce-motion'],
});

export function revealContent(element) {
    active.get(element)?.cancel();
    if (reduceMotion() || !element.animate) return;
    const animation = element.animate([{ opacity: .35 }, { opacity: 1 }], {
        duration: 180, easing: 'cubic-bezier(.22,.61,.36,1)',
    });
    active.set(element, animation);
    const release = () => { if (active.get(element) === animation) active.delete(element); };
    animation.addEventListener('finish', release, { once: true });
    animation.addEventListener('cancel', release, { once: true });
}
