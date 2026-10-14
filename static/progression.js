import { toast, errorMessage } from './toasts.js';
const journey = document.querySelector('[data-journey]');
if (journey) {
    const token = document.querySelector('meta[name="csrf-token"]')?.content;
    const form = journey.querySelector('[data-reward-form]');
    const status = form.querySelector('[data-reward-status]');
    let version = 0;
    let saving = false;
    const preview = () => {
        for (const select of form.querySelectorAll('[data-reward-choice]')) {
            const kind = select.dataset.rewardChoice;
            if (kind === 'frame') journey.querySelector('[data-reward-preview-avatar]').dataset.avatarStyle = select.value;
            if (kind === 'card') journey.querySelector('[data-reward-preview-card]').dataset.cardStyle = select.value;
            if (kind === 'title') journey.querySelector('[data-reward-preview-title]').textContent = select.selectedOptions[0].textContent;
            if (kind === 'badge') {
                const badge = journey.querySelector('[data-reward-preview-badge]');
                badge.textContent = select.value ? select.selectedOptions[0].textContent : '';
                badge.hidden = !select.value;
            }
        }
    };
    form.addEventListener('change', () => { version++; preview(); status.textContent = 'Prévia atualizada. Salve para aplicar.'; });
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (saving) return;
        saving = true;
        const submitted = version;
        const button = form.querySelector('button[type="submit"]');
        button.disabled = true;
        status.textContent = 'Salvando…';
        const payload = Object.fromEntries(new FormData(form));
        delete payload.csrf_token;
        payload.progression_public = form.elements.progression_public.checked;
        try {
            const response = await fetch(form.action, { method: 'POST', headers: {'Content-Type':'application/json','X-CSRF-Token':token}, body:JSON.stringify(payload), credentials:'same-origin' });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Não foi possível salvar.');
            status.textContent = submitted === version ? 'Personalização salva.' : 'As últimas escolhas ainda não foram salvas.';
            toast(status.textContent, {type: submitted === version ? 'success' : 'warning'});
        } catch (error) {
            status.textContent = submitted === version ? `${errorMessage(error)} Suas escolhas foram mantidas; tente salvar novamente.` : 'Suas novas escolhas foram mantidas. Tente salvar novamente.';
            toast(status.textContent, {type:'error'});
        } finally { saving = false; button.disabled = false; }
    });
    const items = [...journey.querySelectorAll('[data-achievement]')];
    const pagination = journey.querySelector('[data-achievement-pagination]');
    let page = 0;
    const pages = Math.ceil(items.length / 6);
    const showPage = () => {
        items.forEach((item, index) => { item.hidden = Math.floor(index / 6) !== page; });
        journey.querySelector('[data-achievements-page]').textContent = `${page+1} / ${pages}`;
        journey.querySelector('[data-achievements-prev]').disabled = page === 0;
        journey.querySelector('[data-achievements-next]').disabled = page === pages-1;
    };
    if (pages > 1) {
        pagination.hidden = false;
        showPage();
        journey.querySelector('[data-achievements-prev]').addEventListener('click',()=>{ page--; showPage(); });
        journey.querySelector('[data-achievements-next]').addEventListener('click',()=>{ page++; showPage(); });
    }
    for (const label of journey.querySelectorAll('[data-quota-reset]')) {
        const tomorrow = new Date();
        tomorrow.setUTCHours(24,0,0,0);
        label.textContent = new Intl.DateTimeFormat('pt-BR',{hour:'2-digit',minute:'2-digit',timeZoneName:'short'}).format(tomorrow);
    }
    const syncStatus = journey.querySelector('[data-journey-status]');
    try {
        const response = await fetch(journey.dataset.syncUrl,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:'{}',credentials:'same-origin'});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Falha ao atualizar a jornada.');
        if (data.notice) {
            syncStatus.textContent = data.notice;
            toast(data.notice, {type:'info',action:{label:'Ver recompensas',href:location.pathname+'#personalizar'}});
        }
        if (data.changed) {
            // Only this server-rendered, read-only summary is replaced. The
            // equipment form and any choices made during sync stay intact.
            journey.querySelector('[data-progression-summary]').outerHTML = data.summary_html;
            const link = document.createElement('a'); link.href = location.href; link.textContent = ' Ver novos desbloqueios';
            syncStatus.append(link);
        }
    } catch (_) {
        syncStatus.textContent = 'Não foi possível atualizar os marcos. Use “Atualizar marcos de permanência” para tentar novamente.';
        toast(syncStatus.textContent, {type:'warning'});
    }
}
