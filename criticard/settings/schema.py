"""Shared preference defaults and Portuguese UI metadata."""
from ..progression.catalog import REWARDS

SECTIONS = {
    'jornada': {'title':'Jornada e recompensas','icon':'sparkles','description':'Personalize os adornos e escolha o que compartilhar.'},
    'aparencia': {'title': 'Aparência', 'icon': 'monitor', 'description': 'Deixe o Criti-CARD com a sua cara.'},
    'feed': {'title': 'Feed e cards', 'icon': 'compass', 'description': 'Escolha como descobrir novas críticas.'},
    'notificacoes': {'title': 'Notificações', 'icon': 'bell', 'description': 'Receba apenas os avisos que fazem sentido para você.'},
    'privacidade': {'title': 'Privacidade', 'icon': 'shield', 'description': 'Decida quem pode entrar em contato com você.'},
    'chat': {'title': 'Chat', 'icon': 'message', 'description': 'Ajuste sua experiência nas conversas.'},
    'conta': {'title': 'Conta e segurança', 'icon': 'user', 'description': 'Cuide da senha, das sessões e dos seus dados.'},
    'bloqueados': {'title': 'Pessoas bloqueadas', 'icon': 'eye-off', 'description': 'Gerencie as pessoas que você bloqueou.'},
}


def _field(section, kind, default, label, help_text, choices=None):
    result = {'section': section, 'kind': kind, 'default': default, 'label': label, 'help': help_text}
    if choices is not None:
        result['choices'] = choices
    return result


FIELDS = {
    'progression_public': _field('jornada','boolean',False,'Exibir jornada no perfil e nos cards','Compartilhe apenas nível, tier e adornos. Seu extrato continua privado.'),
    'progression_notices': _field('jornada','boolean',True,'Avisos de progresso','Receba um aviso discreto para seus desbloqueios.'),
    'progression_title': _field('jornada','choice','title_newcomer','Título','Escolha um título desbloqueado.',{k:v['name'] for k,v in REWARDS.items() if v['kind']=='title'}),
    'progression_frame': _field('jornada','choice','frame_classic','Moldura do avatar','Escolha uma moldura desbloqueada.',{k:v['name'] for k,v in REWARDS.items() if v['kind']=='frame'}),
    'progression_card': _field('jornada','choice','card_classic','Acabamento dos cards','A escolha vale para todos os seus cards.',{k:v['name'] for k,v in REWARDS.items() if v['kind']=='card'}),
    'progression_badge': _field('jornada','choice','','Selo em destaque','O selo fica público apenas quando você ativa a exibição.',{'':'Sem selo',**{k:v['name'] for k,v in REWARDS.items() if v['kind']=='badge'}}),
    'color_scheme': _field('aparencia', 'choice', 'graphite', 'Tema', 'Escolha a paleta da interface.', {'graphite': 'Grafite', 'midnight': 'Meia-noite'}),
    'text_size': _field('aparencia', 'choice', 'standard', 'Tamanho do texto', 'Aumente os textos para uma leitura mais confortável.', {'standard': 'Padrão', 'large': 'Grande'}),
    'reduce_motion': _field('aparencia', 'boolean', False, 'Reduzir movimento', 'Suavize a navegação desativando animações e transições.'),
    'high_contrast': _field('aparencia', 'boolean', False, 'Alto contraste', 'Reforce a separação entre textos, controles e fundos.'),
    'card_hover': _field('aparencia', 'boolean', True, 'Abrir crítica ao passar o mouse', 'Abra a leitura automaticamente ao passar sobre a carta. Você sempre pode abrir por clique.'),
    'card_density': _field('aparencia', 'choice', 'comfortable', 'Densidade dos cards', 'Ajuste o espaço ocupado pelos cards na grade.', {'comfortable': 'Confortável', 'compact': 'Compacta'}),
    'card_excerpt': _field('aparencia', 'boolean', True, 'Resumo nos cards', 'Exiba uma prévia do texto das críticas na grade.'),
    'feed_source': _field('feed', 'choice', 'community', 'Feed inicial', 'Escolha de quem você quer ver críticas ao abrir o feed.', {'community': 'Comunidade', 'following': 'Pessoas que sigo'}),
    'feed_sort': _field('feed', 'choice', 'recent', 'Ordenação inicial', 'Filtros escolhidos na página continuam tendo prioridade.', {'recent': 'Mais recentes', 'highest': 'Maior nota', 'lowest': 'Menor nota', 'oldest': 'Mais antigos'}),
    'feed_category': _field('feed', 'choice', '', 'Categoria inicial', 'Deixe todas as categorias ou escolha sua favorita.', {'': 'Todas as categorias'}),
    'feed_min_score': _field('feed', 'integer', 0, 'Nota mínima', 'Mostre inicialmente cards com nota igual ou maior, de 0 a 100.'),
    'notify_likes': _field('notificacoes', 'boolean', True, 'Curtidas', 'Avise quando alguém curtir um dos seus cards.'),
    'notify_comments': _field('notificacoes', 'boolean', True, 'Comentários', 'Avise quando alguém comentar em um dos seus cards.'),
    'notify_follows': _field('notificacoes', 'boolean', True, 'Novos seguidores', 'Avise quando alguém começar a seguir você.'),
    'notify_friend_requests': _field('notificacoes', 'boolean', True, 'Pedidos de amizade', 'Avise sobre novos pedidos de amizade.'),
    'notify_friend_accepts': _field('notificacoes', 'boolean', True, 'Amizades aceitas', 'Avise quando alguém aceitar seu pedido de amizade.'),
    'message_policy': _field('privacidade', 'choice', 'all', 'Quem pode enviar mensagens', 'A regra vale para novas conversas e novos envios; o histórico continua disponível.', {'all': 'Todas as pessoas', 'friends': 'Somente amigos', 'nobody': 'Ninguém'}),
    'friend_request_policy': _field('privacidade', 'choice', 'all', 'Quem pode pedir amizade', 'Pedidos já recebidos continuam disponíveis para responder.', {'all': 'Todas as pessoas', 'following': 'Pessoas que sigo', 'nobody': 'Ninguém'}),
    'backlog_visibility': _field('privacidade', 'choice', 'private', 'Visibilidade inicial do backlog', 'Aplicada somente às novas obras adicionadas; suas entradas atuais são preservadas.', {'private': 'Privada', 'public': 'Pública'}),
    'chat_enter_send': _field('chat', 'boolean', True, 'Enter para enviar', 'Use Enter para enviar e Shift + Enter para quebrar a linha.'),
    'chat_preview': _field('chat', 'boolean', True, 'Prévia da última mensagem', 'Mostre o resumo da última mensagem na lista de conversas.'),
    'chat_timestamps': _field('chat', 'boolean', True, 'Horários das mensagens', 'Exiba quando cada mensagem foi enviada.'),
}

DEFAULTS = {name: field['default'] for name, field in FIELDS.items()}
SECTION_FIELDS = {section: tuple(name for name, field in FIELDS.items() if field['section'] == section)
                  for section in SECTIONS}
