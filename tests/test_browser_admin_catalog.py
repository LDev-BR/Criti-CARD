"""Administrative catalogue journeys use synthetic users and isolated storage."""
import io
import json
import os
from pathlib import Path
import tempfile

import pytest
from PIL import Image
from sqlalchemy import insert
from werkzeug.security import generate_password_hash

from criticard import create_app
from criticard.backlog.models import BacklogItem
from criticard.config import ROOT
from criticard.db import get_db
from criticard.models import Card, User
from conftest import rows
from test_browser_forms import origin
from test_browser_reading import reading_page as admin_page

pytestmark = pytest.mark.skipif(os.getenv('CRITICARD_BROWSER_TESTS') != '1',
    reason='Set CRITICARD_BROWSER_TESTS=1 to run Edge/Playwright checks')


@pytest.fixture
def app(tmp_path):
    application = create_app({'TESTING': True, 'SECRET_KEY': 'isolated-admin-catalog-browser',
        'DATABASE': str(tmp_path / 'admin.db'), 'DATABASE_URL': None,
        'UPLOAD_FOLDER': str(tmp_path / 'avatars'), 'CAPA_FOLDER': str(tmp_path / 'covers'),
        'ADM_USERNAME': '', 'ADM_SENHA': '', 'ACCOUNT_MAIL_BACKEND': 'disabled',
        'ACCOUNT_SMTP_HOST': '', 'ACCOUNT_SMTP_PASSWORD': '', 'STORAGE_BACKEND': 'local'})
    with application.app_context():
        with get_db() as db:
            for name in ('ALICE', 'ADMIN'):
                db.execute(insert(User).values(username=name, nome=name.title(), apelido='Leitor',
                    about='Histórias para compartilhar.', email=name.lower() + '@example.com',
                    senha=generate_password_hash('Password1!'), admin=int(name == 'ADMIN')))
            db.execute(insert(Card).values(titulo='Elden Ring', capa='catalog:jogos:0',
                obra_id=1, sobre='Uma crítica que precisa permanecer.', nota=92, author_id=1))
            db.execute(insert(BacklogItem).values(user_id=1, work_id=1))
    yield application
    application.extensions['database_engine'].dispose()


def sign_in_admin(page, base):
    page.goto(base + '/')
    page.locator('#username').fill('admin@example.com')
    page.locator('#senha').fill('Password1!')
    page.locator('.form-submit').click()
    page.wait_for_url(base + '/dashboard')


def portrait_file():
    stream = io.BytesIO()
    Image.new('RGB', (700, 1050), '#97783f').save(stream, format='PNG')
    return {'name': 'portrait.png', 'mimeType': 'image/png', 'buffer': stream.getvalue()}


def test_administrator_can_crop_create_edit_retire_and_restore(admin_page, app):
    from playwright.sync_api import expect
    page = admin_page
    base = origin(page)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    sign_in_admin(page, base)
    page.goto(base + '/admin')
    expect(page.get_by_role('heading', name='Administração', exact=True)).to_be_visible()
    for name in ('Gerenciar obras', 'Usuários', 'Moderação', 'Mensagens de suporte', 'Pedidos sobre dados'):
        assert page.get_by_role('heading', name=name, exact=True).is_visible()
    page.locator('.admin-tool-catalog').click()
    page.get_by_role('link', name='Cadastrar obra', exact=True).click()
    page.locator('form[data-validate][novalidate]').wait_for(state='attached')
    page.locator('.form-submit').click()
    expect(page.locator('#capa-error')).to_be_visible()
    assert rows(app, 'SELECT COUNT(*) FROM obras')[0][0] == 30
    page.locator('#titulo').fill('A jornada de QA')
    page.locator('#categoria_id').select_option(label='Jogos')
    expect(page.locator('[data-admin-preview-title]')).to_have_text('A jornada de QA')
    expect(page.locator('[data-admin-preview-category]')).to_have_text('Jogos')
    page.locator('#capa').set_input_files(portrait_file())
    original_upload = page.locator('#cover-preview').get_attribute('src')
    page.locator('[data-crop-image]').click()
    expect(page.locator('#crop-dialog')).to_be_visible()
    page.keyboard.press('Escape')
    assert page.locator('#cover-preview').get_attribute('src') == original_upload
    page.locator('[data-crop-image]').click()
    page.locator('#crop-zoom').focus()
    page.keyboard.press('ArrowRight')
    page.locator('[data-crop-apply]').click()
    expect(page.locator('[data-upload-status]')).to_contain_text('Recorte aplicado')
    assert page.locator('#cover-preview').evaluate('async image => {await image.decode(); return [image.naturalWidth, image.naturalHeight]}') == [1050, 700]
    page.locator('.form-submit').click()
    page.wait_for_url('**/admin/obras*')
    created = rows(app, "SELECT * FROM obras WHERE titulo='A jornada de QA'")[0]
    with Image.open(Path(app.config['CAPA_FOLDER']) / created['capa']) as image:
        assert image.size == (1050, 700)

    # Replacing and resetting an initial illustration must restore its atlas tile.
    page.goto(base + '/admin/obras/1/editar')
    cover = page.locator('[data-admin-preview-image] .catalog-art')
    original_cover = page.locator('#cover-preview').get_attribute('src')
    original_classes = cover.get_attribute('class')
    page.locator('#capa').set_input_files(portrait_file())
    assert 'catalog-art--atlas' not in cover.get_attribute('class')
    page.locator('[data-upload-reset]').click()
    assert page.locator('#cover-preview').get_attribute('src') == original_cover
    assert cover.get_attribute('class') == original_classes
    assert cover.locator('.catalog-art-frame').count() == 1
    page.locator('#titulo').fill('Elden Ring — catálogo QA')
    page.locator('.form-submit').click()
    page.wait_for_url(base + '/admin/obras')
    assert rows(app, 'SELECT capa FROM obras WHERE id=1')[0][0] == 'catalog:jogos:0'

    page.locator('#catalog-q').fill('QA')
    page.locator('#catalog-category').select_option('jogos')
    page.get_by_role('button', name='Filtrar', exact=True).click()
    expect(page.locator('.admin-results-heading h2')).to_have_text('2 obras encontradas')
    assert page.locator('[data-admin-work]').count() == 2
    card_before = tuple(rows(app, 'SELECT * FROM cards WHERE id=1')[0])
    backlog_before = tuple(rows(app, 'SELECT * FROM backlog_items WHERE id=1')[0])
    page.locator('[data-admin-work="1"] .admin-remove').click()
    expect(page.locator('.admin-confirm-copy')).to_contain_text('serão preservadas')
    expect(page.locator('.admin-confirm-copy')).to_contain_text('1 crítica')
    page.get_by_role('button', name='Excluir do catálogo', exact=True).click()
    assert rows(app, 'SELECT active FROM obras WHERE id=1')[0][0] == 1
    page.locator('[name=confirm]').check()
    page.get_by_role('button', name='Excluir do catálogo', exact=True).click()
    page.wait_for_url('**/admin/obras*')
    assert rows(app, 'SELECT active FROM obras WHERE id=1')[0][0] == 0
    assert tuple(rows(app, 'SELECT * FROM cards WHERE id=1')[0]) == card_before
    assert tuple(rows(app, 'SELECT * FROM backlog_items WHERE id=1')[0]) == backlog_before
    page.locator('#catalog-status').select_option('archived')
    page.get_by_role('button', name='Filtrar', exact=True).click()
    expect(page.locator('[data-admin-work="1"] .admin-work-status')).to_have_text('Retirada')
    page.locator('[data-admin-work="1"]').get_by_role('button', name='Reativar Elden Ring — catálogo QA').click()
    assert rows(app, 'SELECT active FROM obras WHERE id=1')[0][0] == 1
    assert rows(app, 'SELECT COUNT(*) FROM obras WHERE id=1')[0][0] == 1
    assert not errors, errors


def test_admin_forms_and_navigation_work_without_javascript_on_mobile(admin_page, app):
    base = origin(admin_page)
    context = admin_page.context.browser.new_context(java_script_enabled=False,
        viewport={'width': 360, 'height': 800})
    page = context.new_page()
    try:
        sign_in_admin(page, base)
        page.goto(base + '/admin')
        assert page.get_by_role('heading', name='Administração', exact=True).is_visible()
        page.locator('.admin-tool-catalog').click()
        page.get_by_role('link', name='Cadastrar obra', exact=True).click()
        assert not page.locator('[data-crop-image]').is_visible()
        page.locator('#titulo').fill('Obra sem JavaScript')
        page.locator('#categoria_id').select_option(label='Livros')
        page.locator('#capa').set_input_files(portrait_file())
        page.locator('.form-submit').click()
        page.wait_for_url(base + '/admin/obras')
        assert rows(app, "SELECT active FROM obras WHERE titulo='Obra sem JavaScript'")[0][0] == 1
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:
        context.close()


def test_admin_screens_desktop_mobile_and_crop_have_no_axe_violations(admin_page):
    from playwright.sync_api import expect
    base = origin(admin_page)
    artifacts = Path(os.getenv('CRITICARD_ADMIN_QA_ARTIFACTS') or tempfile.mkdtemp(prefix='criticard-admin-qa-'))
    artifacts.mkdir(parents=True, exist_ok=True)
    context = admin_page.context.browser.new_context(bypass_csp=True,
        viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
    page = context.new_page()
    errors = []
    report = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text) if message.type in ('error', 'warning') else None)

    def audit(label):
        page.evaluate('document.fonts.ready')
        page.evaluate("async () => {const images = [...document.querySelectorAll('img[src]')]; images.forEach(image => image.loading = 'eager'); await Promise.all(images.map(image => image.decode()));}")
        assert page.title().endswith('Criti-CARD') and page.locator('main').inner_text().strip()
        assert page.locator('h1').count() == 1
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(artifacts / (label + '.png')), full_page=not label.startswith('crop'))
        page.add_script_tag(path=str(ROOT / 'node_modules' / 'axe-core' / 'axe.min.js'))
        violations = page.evaluate("""async () => (await axe.run(document, {runOnly:
            {type:'tag', values:['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']}})).violations
            .map(v => ({id:v.id, impact:v.impact, nodes:v.nodes.map(n => ({target:n.target, summary:n.failureSummary}))}))""")
        report.append({'screen': label, 'url': page.url, 'violations': violations})

    try:
        sign_in_admin(page, base)
        for viewport in ({'width': 1280, 'height': 900}, {'width': 360, 'height': 800}):
            page.set_viewport_size(viewport)
            suffix = '-mobile' if viewport['width'] == 360 else ''
            for label, route in [('hub', '/admin'), ('catalog', '/admin/obras'),
                ('create', '/admin/obras/nova'), ('edit', '/admin/obras/1/editar'),
                ('delete', '/admin/obras/1/excluir'), ('users', '/listar_users'),
                ('support', '/listar_mensagens'), ('delete-user', '/admin_excluir')]:
                assert page.goto(base + route).status == 200
                audit(label + suffix)
            page.goto(base + '/admin/obras/nova')
            page.locator('#capa').set_input_files(portrait_file())
            page.locator('[data-crop-image]').click()
            expect(page.locator('#crop-dialog')).to_be_visible()
            audit('crop' + suffix)
            page.keyboard.press('Escape')
        (artifacts / 'axe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Administrative browser evidence:', artifacts)
        assert not errors, errors
        assert not [entry for entry in report if entry['violations']], json.dumps(report, ensure_ascii=False, indent=2)
    finally:
        context.close()
