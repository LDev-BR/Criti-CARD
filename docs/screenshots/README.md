# Capturas do portfólio

Estas imagens mostram a aplicação Flask real, com os templates Jinja, JavaScript, CSS, fontes e ilustrações locais do repositório. Foram capturadas sem edição visual, em 14 de outubro de 2026, com Playwright e Microsoft Edge headless. O plugin Browser não estava disponível nesta sessão.

**Todos os dados pessoais e textos de participação são fictícios.** Nara, Leo, Maya e Tom foram criados exclusivamente para a demonstração. As críticas, notas, curtidas, comentários, amizade, mensagens, comunidade, coleção privada e eventos de XP também são sintéticos. Os títulos das obras pertencem ao catálogo inicial da aplicação. As imagens das obras são as ilustrações temáticas originais já distribuídas em [`static/catalog/`](../../static/catalog/README.md).

O tema é **Grafite**, a preferência padrão da aplicação, com fundos escuros e detalhes dourados. O navegador usa escala de pixels 1, idioma `pt-BR`, fuso UTC e movimento reduzido. Todas as imagens mostram somente a área visível do navegador, sem moldura ou composição posterior.

| Arquivo | Página | Dimensões | Estado demonstrado |
| --- | --- | --- | --- |
| [discovery-desktop.png](discovery-desktop.png) | `/feed` | 1440 × 960 | Descoberta, atalhos e obras em alta |
| [reviews-desktop.png](reviews-desktop.png) | `/criticas` | 1440 × 960 | Filtros, autores, notas e críticas |
| [catalog-desktop.png](catalog-desktop.png) | `/catalogo` | 1440 × 960 | Catálogo, ilustrações e ações de coleção |
| [community-desktop.png](community-desktop.png) | `/comunidades/entre-paginas-e-telas` | 1440 × 960 | Comunidade aberta e suas publicações temáticas |
| [chat-desktop.png](chat-desktop.png) | `/mensagens/1` | 1440 × 960 | Conversa privada após um envio real em tempo real |
| [journey-mobile.png](journey-mobile.png) | `/jornada` | 390 × 844 | Jornada privada da conta fictícia: nível, XP e acessos sociais |

O [manifesto de captura](manifest.json) registra horário UTC, canal e versão do navegador, rotas, títulos, dimensões, tamanho e SHA-256 de cada PNG, além das verificações executadas. Ele é recriado a cada execução.

## Reproduzir

O gerador está em [`scripts/capture_portfolio.py`](../../scripts/capture_portfolio.py). Execute os comandos a partir da raiz do repositório. Playwright já consta no conjunto opcional [`requirements-browser.txt`](../../requirements-browser.txt); não é uma dependência de execução do app.

No Windows, com Microsoft Edge instalado:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
.\.venv\Scripts\python.exe scripts\capture_portfolio.py --channel msedge
```

Neste workspace, o comando usado foi:

```powershell
.\.runtime\python\python.exe scripts\capture_portfolio.py --channel msedge
```

No Linux, com Chromium gerenciado pelo Playwright:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-browser.txt
python -m playwright install --with-deps chromium
python scripts/capture_portfolio.py
```

`--channel` permite escolher outro canal Chromium disponível. `PLAYWRIGHT_CHANNEL` também é respeitada; sem essa variável, o padrão é `msedge` no Windows e o Chromium do Playwright nos demais sistemas. Exemplo para um canal instalado:

```powershell
$env:PLAYWRIGHT_CHANNEL = 'msedge'
.\.venv\Scripts\python.exe scripts\capture_portfolio.py --output docs/screenshots
```

O destino padrão é `docs/screenshots`. Um destino alternativo deve ser um diretório dedicado dentro do repositório; diretórios internos e de dados privados são recusados. A execução substitui apenas os seis PNGs conhecidos e `manifest.json`, depois que todas as capturas e verificações passarem. Não remove o diretório de saída nem seus outros arquivos.

## Isolamento e verificação

O script desabilita a leitura de `.env` e neutraliza as configurações herdadas de banco, administrador, SMTP e S3. Ele chama `create_app()` com configuração explícita de desenvolvimento, segredo fictício, armazenamento local e serviço de e-mail desabilitado. Não importa `app.py` e não executa `run.ps1`.

Um diretório temporário contém o SQLite, avatares, capas, instância e cópia dos assets públicos. As migrações são aplicadas exclusivamente nesse banco. A cópia de `static/` exclui `uploads/` e `cards/`; nenhum upload de usuário é carregado. O histórico de XP é construído com operações reais do serviço de progressão sobre as contas e contribuições fictícias, sem alterar as regras de acesso do app.

Um servidor local escuta somente em `127.0.0.1`, com porta efêmera. O navegador bloqueia destinos externos e entra pela tela de login, preservando CSRF e a identidade normal da sessão. A execução valida resposta HTTP, título e conteúdo de cada página, carregamento das fontes, ausência de erros de console e ausência de rolagem horizontal. Também exerce a busca dinâmica do catálogo e envia uma mensagem verdadeira pela interface de chat antes da captura final dessa página.

Ao terminar, o navegador, servidor, conexões e diretório temporário são encerrados. As capturas não acessam `instance/criticard.db`, uploads reais, contas existentes ou serviços externos. Esta verificação cobre essas seis páginas, um viewport desktop e um mobile; não substitui a suíte de testes da aplicação.

O conteúdo e o processo são reproduzíveis. Horários, datas, versão do navegador e renderização de fontes podem variar entre execuções e sistemas; não se pretende obter igualdade de pixels entre plataformas.
