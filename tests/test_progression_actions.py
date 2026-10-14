from datetime import timedelta

import pytest
from sqlalchemy import select

from conftest import post, rows
from criticard.db import get_db
from criticard.models import Card, utcnow
from criticard.backlog.service import add_item, update_item
from criticard.social.service import create_comment


def balance(app):
    return rows(app,'SELECT xp FROM progression_profiles WHERE user_id=1')[0][0]


def test_publish_edit_delete_recreate_and_complete_are_idempotent(alice,app):
    data = dict(obra_id='1',sobre='Uma crítica válida.',nota='90')
    assert post(alice,'/cadastro_cards',data).status_code==302
    assert balance(app)==50
    cid = rows(app,'SELECT id FROM cards WHERE author_id=1 AND obra_id=1')[0][0]
    assert post(alice,f'/editar_card/{cid}',{**data,'sobre':'Uma crítica alterada.'}).status_code==302
    assert balance(app)==50
    assert post(alice,f'/deletar_card/{cid}').status_code==302
    assert post(alice,'/cadastro_cards',data).status_code==302
    assert balance(app)==50
    with app.app_context():
        item,_ = add_item(1,dict(obra_id=1,status='completed'))
        update_item(1,item['id'],dict(status='planned'))
        update_item(1,item['id'],dict(status='completed'))
    assert balance(app)==65


def test_backlog_noop_does_not_register_new_week(app,monkeypatch):
    with app.app_context():
        item,_ = add_item(1,dict(obra_id=1))
        later = utcnow()+timedelta(days=8)
        monkeypatch.setattr('criticard.backlog.service.utcnow',lambda:later)
        update_item(1,item['id'],dict(status='planned'))
        assert get_db().execute('SELECT xp FROM progression_profiles WHERE user_id=1').scalar()==10
        update_item(1,item['id'],dict(status='in_progress'))
        assert get_db().execute('SELECT xp FROM progression_profiles WHERE user_id=1').scalar()==20


def test_new_comment_participates_but_login_has_no_visit_xp(alice,app):
    assert balance(app)==0
    with app.app_context():
        create_comment(1,1,'Uma observação.')
        create_comment(1,1,'Outra observação.')
    assert balance(app)==10


def test_failed_progression_rolls_back_publication(alice,app,monkeypatch):
    def fail(*args):
        raise RuntimeError('failed grant')
    monkeypatch.setattr('criticard.progression.service.reconcile_grants',fail)
    with pytest.raises(RuntimeError):
        post(alice,'/cadastro_cards',dict(obra_id=1,sobre='Crítica.',nota=90))
    assert rows(app,'SELECT COUNT(*) FROM cards WHERE obra_id=1')[0][0]==0
    assert balance(app)==0
