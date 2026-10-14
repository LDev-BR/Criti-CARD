"""Real page/context effects of account-owned settings, using isolated accounts."""
import re
from urllib.parse import urlsplit

from test_chat import app, member, action


def test_settings_page_and_sections_require_login(app):
    anonymous = app.test_client()
    assert anonymous.get('/configuracoes').status_code == 302
    client, _ = member(app, 1)
    page = client.get('/configuracoes')
    assert page.status_code == 200
    assert 'Configurações' in page.text and 'data-settings-nav' in page.text
    for section in ('aparencia', 'feed', 'notificacoes', 'privacidade', 'chat', 'conta', 'bloqueados'):
        assert client.get('/configuracoes?secao=' + section).status_code == 200
    assert 'data-settings-form' in page.text


def test_saved_appearance_is_applied_on_other_pages_and_reset_is_scoped(app):
    client, token = member(app, 1)
    response = action(client, token, '/configuracoes/aparencia', {
        'color_scheme': 'midnight', 'text_size': 'large', 'reduce_motion': True,
        'high_contrast': True, 'card_hover': False, 'card_density': 'compact', 'card_excerpt': False})
    assert response.status_code == 200
    page = client.get('/criticas').text
    assert 'data-theme="midnight"' in page and 'data-text-size="large"' in page
    assert 'data-card-hover="false"' in page and 'data-reduce-motion="true"' in page
    assert action(client, token, '/configuracoes/chat', {'chat_enter_send': False,
        'chat_preview': False, 'chat_timestamps': False}).status_code == 200
    assert action(client, token, '/configuracoes/aparencia/restaurar').status_code == 200
    from criticard.settings.service import get_preferences
    with app.app_context():
        prefs = get_preferences(1)
        assert prefs['color_scheme'] == 'graphite' and prefs['card_hover'] is True
        assert prefs['chat_enter_send'] is False
        assert get_preferences(2)['chat_enter_send'] is True


def test_feed_defaults_yield_to_explicit_filters_and_clear_does_not_reapply(app):
    client, token = member(app, 1)
    assert action(client, token, '/configuracoes/feed', {'feed_source': 'following',
        'feed_sort': 'highest', 'feed_category': 'mangas', 'feed_min_score': 80}).status_code == 200
    page = client.get('/criticas').text
    assert 'value="highest" selected' in page and 'value="80"' in page
    tabs = page.split('aria-label="Escolher feed"')[-1].split('</nav>')[0]
    selected = re.search(r'<a [^>]*aria-current="page"[^>]*>(.*?)</a>', tabs, re.S)
    assert selected and 'Seguindo' in selected.group(1)
    explicit = client.get('/criticas?feed=community&categoria=&nota_min=0&ordem=recent').text
    assert 'value="recent" selected' in explicit and 'value="0"' in explicit
    clear = re.search(r'class="clear-filters"[^>]* href="([^"]+)"', page)
    assert clear
    url = clear.group(1).replace('&amp;', '&')
    cleared = client.get(url).text
    assert 'value="recent" selected' in cleared and 'value="0"' in cleared
    assert 'class="filter-tags"' not in cleared


def test_native_settings_forms_preserve_checkbox_semantics_and_csrf(app):
    client, token = member(app, 1)
    assert client.post('/configuracoes/chat', data={'chat_enter_send': '1'}).status_code == 400
    result = client.post('/configuracoes/chat', data={'csrf_token': token,
        'chat_enter_send': '1', 'chat_timestamps': '1'})
    assert result.status_code == 302 and urlsplit(result.location).path == '/configuracoes'
    from criticard.settings.service import get_preferences
    with app.app_context():
        prefs = get_preferences(1)
        assert prefs['chat_enter_send'] is True and prefs['chat_preview'] is False
    assert 'data-chat-show-preview="false"' in client.get('/mensagens').text


def test_native_password_errors_point_to_the_field_without_retaining_passwords(app):
    client, token = member(app, 1)
    response = client.post('/configuracoes/conta/senha', data={'csrf_token': token,
        'current_password': 'Definitelywrong1!', 'new_password': 'AnotherPass2!',
        'confirm_password': 'AnotherPass2!'})
    assert response.status_code == 302
    page = client.get(response.location).text
    assert re.search(r'id="password-current"[^>]*aria-invalid="true"', page)
    assert 'id="password-current-error"' in page
    assert 'Definitelywrong1!' not in page and 'AnotherPass2!' not in page
    with client.session_transaction() as session:
        assert '_settings_account_error' not in session
