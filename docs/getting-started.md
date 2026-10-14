# Primeiros passos

Este guia prepara uma instalação local com SQLite. Para publicação, siga depois [Configuração](configuration.md) e [Operação](operations.md).

## Requisitos

- Python 3.11 ou superior; Python 3.13 é a versão recomendada e a base do Dockerfile.
- Git para trabalhar com o repositório.
- Node.js 22 ou superior apenas para ferramentas e testes JavaScript; a aplicação Flask não exige um servidor Node.
- Acesso ao índice de pacotes durante a instalação inicial.
- PostgreSQL apenas para produção ou para os testes de integração opcionais.

As dependências Python estão fixadas em [requirements.txt](../requirements.txt). [requirements-dev.txt](../requirements-dev.txt) adiciona pytest, validação YAML e o SDK S3 utilizado nos testes. [requirements-production.txt](../requirements-production.txt) inclui Gunicorn e boto3. As dependências de navegador ficam em [requirements-browser.txt](../requirements-browser.txt).

Execute os comandos na pasta raiz do repositório, onde estão `app.py` e `.env.example`.

## Windows com PowerShell

Crie um ambiente virtual e instale as dependências sem depender da ativação de scripts:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item -LiteralPath .env.example -Destination .env
```

O último comando é para uma instalação nova. Se você já possui `.env`, edite o arquivo existente preservando suas configurações locais.

Para migrar e iniciar:

```powershell
.\.venv\Scripts\python.exe -m flask --app criticard db-upgrade
.\.venv\Scripts\python.exe app.py
```

Também existe o atalho:

```powershell
.\run.ps1
```

O script procura Python em `.venv`, depois em `.runtime/python`, e finalmente usa `py`. Ele executa `db-upgrade` antes do servidor e interrompe a inicialização se a migração falhar. Portanto, execute-o apenas quando quiser migrar o banco configurado e abrir o app.

Para depuração local, `run.ps1 -DebugMode` define `FLASK_DEBUG=1`. Esse modo deve ser usado com dados locais de desenvolvimento.

## Linux ou macOS

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
cp .env.example .env
python -m flask --app criticard db-upgrade
python app.py
```

Se sua distribuição fornece Python 3.11 ou 3.12, substitua `python3.13` pelo executável instalado. Dependências ficam no ambiente virtual do projeto.

## Configuração inicial

O exemplo local já contém:

```dotenv
DATABASE=criticard.db
DATABASE_URL=
ENVIRONMENT=development
HOST=127.0.0.1
PORT=5000
FLASK_DEBUG=0
ACCOUNT_MAIL_BACKEND=disabled
STORAGE_BACKEND=local
```

`DATABASE` relativo é resolvido a partir da raiz do projeto. Com esse exemplo, o arquivo fica em `criticard.db`, não dentro de `instance/`. Quando `DATABASE_URL` está preenchida, ela tem prioridade sobre `DATABASE`.

Sem `SECRET_KEY`, o desenvolvimento cria uma chave persistente em `instance/secret_key`. O modo de produção exige uma chave explícita própria. Não versione o arquivo local, bancos, emails de teste nem imagens enviadas por usuários.

Variáveis já definidas no processo têm prioridade sobre `.env`. Se o terminal herdou uma `DATABASE_URL` de outro ambiente, confira-a antes de executar migrações. A tabela completa e as regras de validação estão em [Configuração](configuration.md).

## Abrir e experimentar

Com o servidor iniciado, abra [http://127.0.0.1:5000](http://127.0.0.1:5000). O servidor iniciado por `app.py` é destinado à execução local.

1. Visite `/feed`, `/catalogo` e `/criticas` para conhecer as páginas públicas.
2. Crie uma conta em `/cadastro` e entre com username ou email.
3. Adicione uma obra do catálogo ao `/backlog`.
4. Publique uma crítica selecionando a obra em `/cadastro_cards`.
5. Experimente filtros, perfil, conexões e preferências.
6. Consulte `/jornada` para entender XP e condições dos espaços sociais.

As migrações criam categorias, obras iniciais e comunidades temáticas. Elas não criam pessoas fictícias ou críticas de demonstração. Um banco novo pode mostrar estados vazios, o que é esperado.

## Primeiro administrador

Para uma instalação nova, preencha os dois campos e um email adequado no `.env`:

```dotenv
ADM_USERNAME=ADMINLOCAL
ADM_SENHA=uma-senha-forte-propria
ADM_EMAIL=seu-email-valido
```

Os valores acima são marcadores de preenchimento, não credenciais utilizáveis. A senha real deve atender à validação do cadastro: 8 a 128 caracteres, maiúscula, minúscula, número e um símbolo de `!@#$%&_*`.

Execute `db-upgrade` novamente. A criação só ocorre se os dois campos estiverem preenchidos e ainda não existir nenhum administrador. Username ou email ocupado por outra conta produz erro; o comando não promove automaticamente uma conta existente.

## Email local sem SMTP

Para explorar recuperação e verificação sem enviar email externo:

```dotenv
ACCOUNT_MAIL_BACKEND=file
ACCOUNT_BASE_URL=http://127.0.0.1:5000
ACCOUNT_OUTBOX_PATH=instance/outbox
ACCOUNT_MAIL_FROM=no-reply@criticard.test
```

Reinicie o app. Os links aparecerão em arquivos `.eml` na caixa de saída privada. O backend `file` aceita somente uma URL local. Os arquivos contêm tokens e devem continuar fora do Git e de `static/`.

## Conferir o ambiente

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd ci --ignore-scripts
npm.cmd test
```

Em Linux/macOS, use `python` com o ambiente ativo e `npm`. Testes de PostgreSQL e navegador ficam desativados até serem explicitamente configurados; consulte [Testes](testing.md) para habilitá-los.

## Problemas comuns

| Sintoma | Verificação |
| --- | --- |
| Falta de uma tabela | Execute `db-upgrade` no banco de desenvolvimento correto |
| Banco diferente do esperado | Confira `DATABASE_URL`, `DATABASE` e variáveis herdadas no terminal |
| PowerShell bloqueia a ativação | Use o caminho direto `.venv\Scripts\python.exe` |
| Porta ocupada | Defina outro `PORT` e ajuste a URL do navegador |
| Recuperação não gera arquivo | Confira backend `file`, URL local e caminho fora de `static/` |
| Entrada em grupo recusada | Consulte nível, tempo e dias de cota em [Progressão](progression.md) |
| Erro de CSRF | Reabra o formulário na sessão atual antes de reenviar |

Para interromper o servidor local, use `Ctrl+C`. Seus dados SQLite persistem entre execuções.
