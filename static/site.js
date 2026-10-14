/** Responsive navigation supplements native links and details elements. */
const nav = document.getElementById('primary-nav');
const toggle = document.querySelector('[data-nav-toggle]');
const navigation = document.querySelector('[data-primary-navigation]');
const account = document.querySelector('[data-account-menu]');
const mobile = window.matchMedia('(max-width:1050px)');
document.documentElement.dataset.navigationReady = 'true';

function setNavigation(open) {
    if (!nav || !toggle || !navigation) return;
    navigation.open = !mobile.matches || open;
    toggle.setAttribute('aria-expanded', String(mobile.matches && open));
    toggle.setAttribute('aria-label', open ? 'Fechar navegação' : 'Abrir navegação');
    if (!open && account) account.open = false;
}

function synchronizeViewport() {
    setNavigation(false);
}

navigation?.addEventListener('toggle', () => {
    toggle?.setAttribute('aria-expanded', String(navigation.open));
    toggle?.setAttribute('aria-label', navigation.open ? 'Fechar navegação' : 'Abrir navegação');
});
mobile.addEventListener('change', synchronizeViewport);
synchronizeViewport();

// Native disclosures remain usable before scripts load and when JS is disabled.
const compactSections = window.matchMedia('(max-width:850px)');
function synchronizeSections() {
    document.querySelectorAll('[data-responsive-disclosure]').forEach(disclosure => {
        disclosure.open = disclosure.hasAttribute('data-keep-open') || !compactSections.matches;
    });
}
compactSections.addEventListener('change', synchronizeSections);
synchronizeSections();

document.addEventListener('click', (event) => {
    if (account?.open && !account.contains(event.target)) account.open = false;
    if (mobile.matches && toggle?.getAttribute('aria-expanded') === 'true' && !event.target.closest('.site-header')) setNavigation(false);
});
document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (account?.open) {
        account.open = false;
        account.querySelector('summary').focus();
    } else if (mobile.matches && toggle?.getAttribute('aria-expanded') === 'true') {
        setNavigation(false);
        toggle.focus();
    }
});

function openSupport() {
    if (location.hash === '#suporte') {
        const support = document.getElementById('suporte');
        if (support) support.open = true;
    }
}
window.addEventListener('hashchange', openSupport);
openSupport();
