# Testes e verificação

A suíte verifica regras de domínio, rotas, persistência, concorrência PostgreSQL e interações do navegador. Este guia apresenta os caminhos disponíveis sem atribuir ao projeto números fixos de aprovação ou cobertura.

## Instalação básica

Com o ambiente Python ativo:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
npm ci --ignore-scripts
npm test
```

No PowerShell, sem ativação de ambiente:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd ci --ignore-scripts
npm.cmd test
```

O workspace também pode oferecer `.runtime/python/python.exe`; esse caminho é uma conveniência local, não um pré-requisito de uma cópia nova.

## Isolamento dos dados

Fixtures criam SQLite, avatares e capas em diretórios temporários. Os testes passam configuração explícita à factory e exercitam migrações no banco descartável. O helper de formulários obtém o CSRF de HTML real; os testes não precisam desativar a proteção.

Nunca aponte testes para `criticard.db`, `instance/criticard.db`, banco publicado ou diretórios de uploads pessoais. Para novos testes, use `tmp_path` e configuração própria, incluindo backend de email e pastas quando a área depender deles.

Os testes de navegador abrem servidores locais em portas livres e usam pessoas fictícias. Algumas provas produzem imagens em `.runtime/`; esses artefatos de execução não são as capturas públicas de portfólio.

## Escolher a verificação relevante

| Alteração | Exemplos de arquivos |
| --- | --- |
| Crítica única e edição | `test_unique_cards.py`, `test_card_editing.py`, `test_curated_cards.py` |
| Coleção | `test_backlog.py`, `test_browser_backlog.py` |
| Login, sessão e formulários | `test_core.py`, `test_session_identity.py`, `test_form_security.py` |
| Email e recuperação | `test_accounts.py`, `test_accounts_worker.py`, `test_accounts_browser.py` |
| Conexões | `test_connections.py`, `test_connections_http.py`, `test_browser_connections.py` |
| Chat | `test_chat.py`, `test_chat_sockets.py`, `test_chat_proxy.py` |
| Comunidades e descoberta | `test_thematic_community_audit.py`, `test_feed_filters.py`, `test_transfer_communities.py` |
| Jornada | `test_progression_policy.py`, `test_progression_actions.py`, `test_progression_http.py` |
| Privacidade | `test_privacy.py`, `test_admin_deletion_privacy.py`, `test_avatar_retirement_privacy.py` |
| Banco e operação | `test_persistence.py`, `test_transfer.py`, `test_production_config.py` |

Exemplo de execução focada:

```bash
python -m pytest -q tests/test_backlog.py tests/test_unique_cards.py
```

Amplie à suíte completa em mudanças transversais, autenticação, privacidade ou esquema. Os nomes acima são pontos de entrada, não uma lista completa nem uma garantia de que só esses arquivos sejam afetados.

## Testes JavaScript

`package.json` executa `node --test tests/*.test.mjs`. Use Node 22 ou superior, inclusive no Windows, para a expansão nativa desse padrão pelo test runner. Os testes atuais cobrem geometria de recorte, paginação de leitura e política de senha.

```bash
npm test
node --test tests/crop-geometry.test.mjs
```

`npm ci` respeita o lockfile e instala também axe-core, utilizado na verificação de acessibilidade do navegador. Não há bundle de frontend a compilar para iniciar Flask.

## PostgreSQL real, opcional

Defina `CRITICARD_TEST_POSTGRES_URL` para um servidor de testes dedicado. A fixture usa a conexão base para criar bancos de nome aleatório `criticard_integration_test_<uuid>` e os remove ao terminar.

O usuário precisa poder criar e remover esses bancos. Use um serviço descartável; não forneça credenciais de uma instalação com dados reais.

PowerShell:

```powershell
$env:CRITICARD_TEST_POSTGRES_URL = 'postgresql+psycopg://criticard_test:senha-local@127.0.0.1:5432/postgres'
.\.venv\Scripts\python.exe -m pytest -q tests/test_postgres.py
Remove-Item Env:CRITICARD_TEST_POSTGRES_URL
```

Linux/macOS:

```bash
CRITICARD_TEST_POSTGRES_URL='postgresql+psycopg://criticard_test:senha-local@127.0.0.1:5432/postgres' \
  python -m pytest -q tests/test_postgres.py
```

Os valores são exemplos de um ambiente descartável, não credenciais existentes. Sem essa variável, as provas PostgreSQL são marcadas como ignoradas. Isso não equivale a verificar comportamento PostgreSQL usando SQLite.

A suíte cobre, entre outros, escrita concorrente, unicidade, revogação de sessões, bloqueios, privacidade e importação. `test_postgres_restore.py` também necessita de `pg_dump` e `pg_restore` compatíveis com o servidor. O helper procura primeiro `CRITICARD_PG_BIN`, depois um runtime portátil local e finalmente o PATH. Para PostgreSQL 18, a CI define `CRITICARD_PG_BIN=/usr/lib/postgresql/18/bin` para selecionar os clientes correspondentes.

## Navegador com Playwright

Instale o grupo opcional e o Chromium:

```bash
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
npm ci --ignore-scripts
```

Em Linux, quando for preciso instalar bibliotecas do sistema e houver permissão para isso, use `python -m playwright install --with-deps chromium`.

Habilite o opt-in no PowerShell:

```powershell
$env:CRITICARD_BROWSER_TESTS = '1'
$env:PLAYWRIGHT_CHANNEL = 'chromium'
.\.venv\Scripts\python.exe -m pytest -q tests/test_browser_connections.py tests/test_browser_chat.py
Remove-Item Env:CRITICARD_BROWSER_TESTS
Remove-Item Env:PLAYWRIGHT_CHANNEL
```

Em Linux/macOS:

```bash
CRITICARD_BROWSER_TESTS=1 PLAYWRIGHT_CHANNEL=chromium \
  python -m pytest -q tests/test_browser_connections.py tests/test_browser_chat.py
```

No Windows, fixtures usam Microsoft Edge quando `PLAYWRIGHT_CHANNEL` não foi definido; em outras plataformas, o default é o Chromium instalado pelo Playwright. Definir `chromium` permite escolher o browser empacotado nas versões atuais do Playwright.

Os testes abrangem layout responsivo, teclado, foco, acessibilidade, estados de leitura, formulários sem JavaScript, reconexão e interação com assets reais. A auditoria automatizada não substitui uma revisão humana de conteúdo e uso.

## Integração contínua

[`ci.yml`](../.github/workflows/ci.yml) executa em pushes para `main`/`master`, pull requests e acionamento manual. Os jobs são:

| Job | Ambiente e verificação |
| --- | --- |
| `python` | Ubuntu com Python 3.11/3.13 e Windows com 3.13; suíte pytest padrão |
| `javascript` | Ubuntu, Node 22/24; instalação por lockfile e testes Node |
| `postgres` | Ubuntu, Python 3.13, serviço PostgreSQL 18 descartável; suíte com opt-in PostgreSQL e clientes 18 |
| `browser` | Ubuntu, Python 3.13, Node 24 e Chromium; todos os `test_browser_*.py` e `test_accounts_browser.py` |

Os relatórios JUnit de falha são guardados por sete dias. Actions oficiais são fixadas por SHA e o workflow usa `contents: read`; ele não publica a aplicação nem precisa de credenciais de produção. [Dependabot](../.github/dependabot.yml) propõe atualizações semanais agrupadas de GitHub Actions.

Criar o workflow e validá-lo localmente não fornece um resultado de execução hospedada. O histórico de jobs só existirá quando o repositório for enviado ao GitHub e a CI executar.

## Relatar resultados úteis

Registre comando, ambiente e resultado observado. Informe testes ignorados por ausência de PostgreSQL ou navegador; não os apresente como aprovados. Quando houver falha, preserve o caso reproduzível com dados fictícios e sem tokens, outbox ou parâmetros privados.

`run.ps1` aplica migrações ao banco configurado e abre o app. Ele não é um comando de teste. Para preparação de contribuição e critérios de revisão, consulte [CONTRIBUTING](../CONTRIBUTING.md).
