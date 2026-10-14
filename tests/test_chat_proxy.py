"""Exercise the actual WSGI transport, including trusted proxy headers."""
import json

import pytest
from sqlalchemy import insert
from werkzeug.security import generate_password_hash

from criticard import create_app
from criticard.db import get_db
from criticard.models import User
from test_chat import member


@pytest.mark.parametrize('proxy_hops,connected', [(1, True), (0, False)])
def test_chat_https_origin_requires_configured_proxy_trust(tmp_path, proxy_hops, connected):
    app = create_app({'TESTING': True, 'SECRET_KEY': 'proxy-transport-test-key',
        'PROXY_HOPS': proxy_hops, 'DATABASE': str(tmp_path / 'chat.db'),
        'UPLOAD_FOLDER': str(tmp_path / 'avatars'), 'CAPA_FOLDER': str(tmp_path / 'covers')})
    try:
        with app.app_context():
            db = get_db()
            with db:
                db.execute(insert(User).values(id=1, username='ALICE', nome='Alice', apelido='Leitora', about='',
                    email='alice@example.com', senha=generate_password_hash('Password1!')))
        client, csrf = member(app, 1)
        headers = {'Origin': 'https://localhost', 'X-Forwarded-Proto': 'https'}
        opened = client.get('/socket.io/?EIO=4&transport=polling', headers=headers)
        assert opened.status_code == 200
        sid = json.loads(opened.text[1:])['sid']
        path = '/socket.io/?EIO=4&transport=polling&sid=' + sid
        try:
            sent = client.post(path, headers=headers, content_type='text/plain',
                data='40/chat,' + json.dumps({'csrf_token': csrf}))
            assert sent.status_code == 200
            packet = client.get(path, headers=headers).text
            assert packet.startswith('40/chat,' if connected else '44/chat,'), packet
        finally:
            client.post(path, headers=headers, content_type='text/plain', data='1')
    finally:
        app.extensions['database_engine'].dispose()
