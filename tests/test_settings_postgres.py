"""Real PostgreSQL JSON persistence and privacy serialization."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, current_thread
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select

from criticard.db import get_db
from criticard.settings.models import UserSettings
from criticard.settings.service import get_preferences, save_preferences
from test_postgres import pg_app, pg_database_url, in_app


def test_postgres_section_updates_merge_one_preference_document(pg_app):
    barrier = Barrier(2)
    def save(section, values):
        with pg_app.app_context():
            barrier.wait(timeout=5)
            return save_preferences(1, section, values)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(save, 'aparencia', {'color_scheme': 'midnight', 'high_contrast': True})
        second = pool.submit(save, 'chat', {'chat_enter_send': False})
        first.result(timeout=10)
        second.result(timeout=10)
    with pg_app.app_context():
        prefs = get_preferences(1)
        assert prefs['color_scheme'] == 'midnight' and prefs['high_contrast'] is True
        assert prefs['chat_enter_send'] is False and prefs['backlog_visibility'] == 'private'
        assert get_preferences(2)['chat_enter_send'] is True
        assert get_db().execute(select(func.count()).select_from(UserSettings)).scalar() == 1


@pytest.mark.parametrize('interaction', ['message', 'friend'])
def test_postgres_privacy_change_precedes_a_waiting_interaction(pg_app, interaction):
    from criticard.chat.service import ChatError, send_message, start_conversation
    from criticard.chat.models import Message
    from criticard.social.connections import change_friendship
    from criticard.social.models import Friend
    from criticard.social.service import SocialError
    with pg_app.app_context():
        conversation = start_conversation(1, 2)[0]['id'] if interaction == 'message' else None
    locked, attempted, release = Event(), Event(), Event()
    engine = pg_app.extensions['database_engine']
    def after_write(connection, cursor, statement, parameters, context, executemany):
        if current_thread().name.startswith('privacy-writer') and 'INSERT INTO user_settings' in statement:
            locked.set()
            assert release.wait(timeout=10)
    def before_lock(connection, cursor, statement, parameters, context, executemany):
        if current_thread().name.startswith('privacy-actor') and 'FOR UPDATE' in statement:
            attempted.set()
    def write():
        key = 'message_policy' if interaction == 'message' else 'friend_request_policy'
        return in_app(pg_app, lambda: save_preferences(2, 'privacidade', {key: 'nobody'}))
    def interact():
        with pg_app.app_context():
            with pytest.raises((ChatError, SocialError)) as error:
                if interaction == 'message':
                    send_message(1, conversation, 'Não deve ser salva', str(uuid4()))
                else:
                    change_friendship(1, 2, 'request')
            return error.value.status
    event.listen(engine, 'after_cursor_execute', after_write)
    event.listen(engine, 'before_cursor_execute', before_lock)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='privacy-writer') as writers, \
             ThreadPoolExecutor(max_workers=1, thread_name_prefix='privacy-actor') as actors:
            writer = writers.submit(write)
            assert locked.wait(timeout=10)
            actor = actors.submit(interact)
            try:
                assert attempted.wait(timeout=10)
            finally:
                release.set()
            writer.result(timeout=10)
            assert actor.result(timeout=10) == 403
        with pg_app.app_context():
            model = Message if interaction == 'message' else Friend
            assert get_db().execute(select(func.count()).select_from(model)).scalar() == 0
    finally:
        release.set()
        event.remove(engine, 'after_cursor_execute', after_write)
        event.remove(engine, 'before_cursor_execute', before_lock)
