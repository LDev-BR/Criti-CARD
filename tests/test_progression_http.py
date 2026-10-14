import re

import pytest
from sqlalchemy import select

from conftest import post
from criticard.db import get_db
from criticard.progression.models import ExperienceEvent, RewardGrant
from criticard.progression.service import record_action, record_event, sync_user
from criticard.models import utcnow
from criticard.settings.service import get_preferences, save_preferences


def json_post(client,path,payload,csrf=True):
    page = client.get('/dashboard')
    token = re.search(r'name="csrf-token" content="([^"]+)"',page.text)
    return client.post(path,json=payload,headers={'X-CSRF-Token':token.group(1)} if csrf and token else {})


def test_private_journey_auth_csrf_and_no_client_xp(client,alice):
    assert client.get('/jornada',headers={'Accept':'application/json'}).status_code==200  # shared authenticated client
    assert json_post(alice,'/jornada/sincronizar',{},csrf=False).status_code==400
    for payload in ({'xp':9999},{'user_id':2},{'event':'card:1'},[],{'user_id':True}):
        assert json_post(alice,'/jornada/sincronizar',payload).status_code==422
    assert json_post(alice,'/jornada/sincronizar',{}).status_code==200
    assert alice.get('/jornada?user_id=2').status_code==404
    assert alice.get('/jornada?page=999999999999').status_code==404
    assert alice.get('/jornada?page=false').status_code==404


def test_anonymous_cannot_read_journey(client):
    assert client.get('/jornada',headers={'Accept':'application/json'}).status_code==401


@pytest.mark.parametrize('slug', ['frame_gold','frame_css_injection',{},True])
def test_locked_or_malformed_reward_rejected(alice,slug):
    assert json_post(alice,'/jornada/personalizar',{'progression_frame':slug}).status_code==400


def test_equipment_persists_without_overwriting_other_settings(alice,app):
    with app.app_context():
        save_preferences(1,'chat',{'chat_enter_send':False})
        with get_db() as db:
            now = utcnow()
            for work_id in range(1,14):
                record_event(db,1,'card_published',f'card:{work_id}',now,
                    work_id=work_id,category_id=1,origin='history')
            sync_user(db,1,now)
    result = json_post(alice,'/jornada/personalizar',{'progression_badge':'badge_level_005'})
    assert result.status_code==200, result.text
    with app.app_context():
        preferences = get_preferences(1)
        assert preferences['progression_badge']=='badge_level_005'
        assert preferences['chat_enter_send'] is False
        assert preferences['progression_public'] is False


def test_gets_do_not_mutate_progression_and_cache_is_private(alice,app):
    with app.app_context():
        before = get_db().execute(select(ExperienceEvent)).fetchall()
        grants_before = get_db().execute(select(RewardGrant)).fetchall()
    response = alice.get('/jornada')
    assert response.status_code==200
    assert response.headers['Cache-Control']=='no-store'
    with app.app_context():
        assert get_db().execute(select(ExperienceEvent)).fetchall()==before
        assert get_db().execute(select(RewardGrant)).fetchall()==grants_before


def test_export_contains_only_owners_progression(alice):
    data = alice.get('/configuracoes/conta/exportar').get_json()
    assert data['progression']['profile']['user_id']==1
    assert all(row['user_id']==1 for row in data['progression']['events'])


def test_render_journey_dashboard_and_consistent_public_cosmetics(alice,app):
    with app.app_context():
        with get_db() as db:
            now = utcnow()
            for work_id in range(1,29):
                record_event(db,1,'card_published',f'card:{work_id}',now,
                    work_id=work_id,category_id=1,origin='history')
            sync_user(db,1,now)
        save_preferences(1,'jornada',dict(progression_public=True,progression_frame='frame_slate',progression_card='card_slate'))
    assert 'Minha jornada' in alice.get('/dashboard').text
    journey = alice.get('/jornada').text
    assert 'data-reward-form' in journey and 'disabled' in journey
    assert 'Exibir jornada' in journey and 'Extrato privado' in journey
    assert 'data-card-style="card_slate"' in alice.get('/cadastro_cards').text
    post(alice,'/cadastro_cards',dict(obra_id=1,sobre='Crítica válida.',nota=90))
    public = app.test_client().get('/perfil/ALICE').text
    assert 'data-card-style="card_slate"' in public
    assert 'data-avatar-style="frame_slate"' in public
    assert 'Nível 11 · Aprendiz' in public
    assert 'Extrato privado' not in public and 'experience_events' not in public


def test_account_deletion_cascades_progression(alice,app):
    assert post(alice,'/delete',dict(senha='Password1!')).status_code==302
    with app.app_context():
        for table in ('progression_profiles','experience_events','achievement_grants','reward_grants'):
            assert get_db().execute(f'SELECT COUNT(*) FROM {table} WHERE user_id=1').scalar()==0


def test_native_equipment_form_preserves_notice_preference(alice,app):
    assert post(alice,'/jornada/personalizar',dict(progression_title='title_newcomer',
        progression_frame='frame_classic',progression_card='card_classic',progression_badge='')).status_code==302
    with app.app_context():
        assert get_preferences(1)['progression_notices'] is True
