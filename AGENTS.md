# AGENTS.md

## Projeto

- Criti-CARD é uma aplicação Flask organizada por funcionalidades, com SQLAlchemy, Alembic, templates Jinja e JavaScript/CSS próprios.
- `criticard/__init__.py` define `create_app()` e registra os blueprints. Prefira seguir o padrão do módulo da funcionalidade alterada.
- Comunidades temáticas (publicações, comentários e reações) e chats em grupo (mensagens em tempo real) são áreas separadas. `/feed` é a página de descoberta; `/criticas` é o feed de críticas.
- SQLite é usado no desenvolvimento local; PostgreSQL é o alvo de publicação. O chat usa Flask-SocketIO.

## Estrutura

- `criticard/`: rotas, serviços, modelos e regras por área.
- `templates/` e `static/`: interface Jinja e seus estilos, scripts, fontes e imagens locais.
- `migrations/versions/`: revisões Alembic.
- `tests/`: testes pytest; `tests/*.test.mjs`: testes JavaScript executados pelo Node.
- `docs/`: documentação de produto, operação, privacidade e decisões visuais.

## Convenções

- Mantenha regras de negócio no módulo/serviço da funcionalidade quando houver essa separação; deixe rotas cuidarem do HTTP e templates da apresentação.
- A autorização deve ser validada no servidor em toda rota, ação de chat e consulta de dado privado. Preserve CSRF nas mutações, bloqueios, visibilidade e regras de privacidade; não dependa de controles da interface para proteger dados.
- Para mudar o esquema, crie uma nova revisão Alembic em vez de editar uma revisão já aplicada. Preserve dados existentes e compatibilidade com SQLite e PostgreSQL.
- Preserve HTML semântico, acessibilidade, responsividade e os fallbacks sem JavaScript já oferecidos pelos fluxos server-rendered. Use os assets locais existentes.
- Coloque regressões junto aos testes da funcionalidade alterada. Use bancos descartáveis nos testes; nunca os aponte para `instance/criticard.db`.

## Verificação e execução

- Com o ambiente Python ativo: `python -m pytest -q`. No PowerShell com o runtime deste workspace: `.\.runtime\python\python.exe -m pytest -q`.
- Testes JavaScript: `npm.cmd test` no PowerShell ou `npm test` em outros shells.
- Prefira os testes relevantes para a mudança; amplie para a suíte completa em alterações transversais, de autenticação, privacidade ou esquema.
- `run.ps1` aplica migrações ao banco configurado antes de iniciar a aplicação. Use-o para rodar o app local conscientemente, não como comando de teste.

## Referências por tarefa

Leia somente a documentação necessária à tarefa: `docs/social-spaces-discovery.md` para descoberta, follows, comunidades e chats em grupo; `docs/progression.md` para XP e acesso por nível; `docs/privacy-operations.md` para privacidade e exclusão de conta; `docs/admin-catalog.md` para o catálogo administrativo; `docs/operations.md` para banco, backup e publicação; `docs/design/connections-visual.md` para a interface de conexões. Planos e specs em `docs/superpowers/` registram trabalhos específicos; consulte-os quando a tarefa continuar aquele trabalho.
