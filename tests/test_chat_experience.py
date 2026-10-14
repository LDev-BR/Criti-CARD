"""Public presentation contracts for the shared messages workspace."""
from flask import template_rendered

from test_chat import app, start


def test_conversation_peer_has_a_public_avatar_without_private_fields(app):
    client, _, conversation_id = start(app)
    data = client.get(f'/mensagens/{conversation_id}', headers={'Accept': 'application/json'}).json
    assert data['conversation']['peer'] == {
        'id': 2, 'username': 'BOB', 'name': 'Bob',
        'avatar_url': '/static/default-avatar.svg',
    }


def test_detail_provides_the_other_conversations_for_navigation(app):
    client, _, conversation_id = start(app)
    contexts = []

    def capture(sender, template, context, **extra):
        contexts.append(context)

    template_rendered.connect(capture, app)
    try:
        response = client.get(f'/mensagens/{conversation_id}')
    finally:
        template_rendered.disconnect(capture, app)
    assert response.status_code == 200
    assert [item['id'] for item in contexts[-1]['conversations']] == [conversation_id]
    assert contexts[-1]['unread_count'] == 0


def test_conversation_avatars_work_in_background_application_context(app):
    from criticard.chat.service import conversation_summary
    _, _, conversation_id = start(app)
    with app.app_context():
        peer = conversation_summary(1, conversation_id)['peer']
    assert peer['avatar_url'] == '/static/default-avatar.svg'
