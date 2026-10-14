# Configuração

A referência principal é [criticard/config.py](../criticard/config.py). Este guia distingue variáveis lidas do ambiente, valores fixos da aplicação e opções usadas apenas por ferramentas.

## Precedência e caminhos

1. `defaults()` carrega `.env` na raiz pelo python-dotenv; variáveis já presentes no processo não são sobrescritas.
2. Os defaults são aplicados a `app.config`.
3. Um dicionário passado a `create_app(config)` sobrescreve esses valores.
4. Se esse dicionário define `DATABASE` e omite `DATABASE_URL`, a factory limpa a URL herdada, permitindo isolamento nos testes.
5. Para a engine, uma `DATABASE_URL` preenchida tem prioridade sobre `DATABASE`.

`DATABASE`, `UPLOAD_FOLDER` e `CAPA_FOLDER` relativos são resolvidos a partir da raiz do repositório. O default da caixa de saída também é absoluto, mas um `ACCOUNT_OUTBOX_PATH` relativo é resolvido pelo módulo de email a partir do diretório corrente; execute app e worker na raiz ou configure um caminho absoluto.

Flags `SESSION_COOKIE_SECURE` e `FLASK_DEBUG` só ativam com a string `1`. `PORT`, `PROXY_HOPS` e `ACCOUNT_SMTP_PORT` são convertidos para inteiro. `TRUSTED_HOSTS` é separado por vírgulas, com espaços removidos.

## Aplicação e banco

| Variável | Default no código | Uso |
| --- | --- | --- |
| `SECRET_KEY` | Ausente; chave local persistente em `instance/secret_key` | Assinatura da sessão e HMACs |
| `DATABASE` | `<raiz>/criticard.db` | Arquivo SQLite se não houver URL |
| `DATABASE_URL` | Ausente | URL SQLAlchemy de SQLite ou PostgreSQL |
| `ENVIRONMENT` | `development` | Ativa validações e HSTS quando exatamente `production` |
| `HOST` | `127.0.0.1` | Bind do servidor local em `app.py` |
| `PORT` | `5000` | Porta do servidor local |
| `FLASK_DEBUG` | `0` | Depuração local |
| `SESSION_COOKIE_SECURE` | `0` | Cookie enviado somente por HTTPS quando ativo |
| `TRUSTED_HOSTS` | Lista ausente | Hosts aceitos pelo Flask |
| `PROXY_HOPS` | `0` | De zero a três proxies confiáveis para IP/protocolo |
| `UPLOAD_FOLDER` | `<raiz>/static/uploads` | Avatares locais |
| `CAPA_FOLDER` | `<raiz>/static/cards` | Capas locais |
| `ADM_USERNAME` | Vazio | Username do primeiro administrador |
| `ADM_SENHA` | Vazio | Senha do primeiro administrador |
| `ADM_EMAIL` | `admin@example.com` | Email de bootstrap administrativo |

Exemplo de URL PostgreSQL:

```dotenv
DATABASE_URL=postgresql+psycopg://usuario:senha@127.0.0.1:5432/criticard
```

Substitua os campos por dados do ambiente e codifique caracteres especiais de credenciais na URL. As formas `postgres://` e `postgresql://` são normalizadas para psycopg pelo código. Apenas SQLite e PostgreSQL são suportados.

O bootstrap administrativo ocorre nos comandos de migração, não em cada acesso HTTP. Ele exige username/senha válidos e só cria uma conta quando ainda não existe administrador. Os campos vazios de `.env.example` evitam uma credencial pública padrão.

## Email de conta

| Variável | Default no código | Uso |
| --- | --- | --- |
| `ACCOUNT_MAIL_BACKEND` | `disabled` | `disabled`, `file` ou `smtp` |
| `ACCOUNT_BASE_URL` | Vazio | Base dos links de conta, sem query, fragmento ou credenciais |
| `ACCOUNT_OUTBOX_PATH` | `<raiz>/instance/outbox` | Spool privado `.eml` |
| `ACCOUNT_MAIL_FROM` | Vazio | Remetente; `file` possui fallback local |
| `ACCOUNT_SMTP_HOST` | Vazio | Servidor SMTP |
| `ACCOUNT_SMTP_PORT` | `587` | Porta; para SSL configure explicitamente `465` se for a porta do serviço |
| `ACCOUNT_SMTP_USERNAME` | Vazio | Login SMTP opcional |
| `ACCOUNT_SMTP_PASSWORD` | Vazio | Senha correspondente ao login |
| `ACCOUNT_SMTP_TLS` | `starttls` | Apenas `starttls` ou `ssl` para SMTP |

`disabled` não gera links de email. `file` grava a mensagem e permite examinar links localmente, sem transmissão SMTP. Ele exige host local na URL base. `smtp` também grava o spool; o envio é feito pelo worker ou pelo comando `accounts-send-mail`.

A caixa de saída não pode estar dentro de `static/`. Ela contém links de recuperação e dados de destinatário; deve ser privada e compartilhada entre processo web e worker. Os valores de URL e remetente presentes em `.env.example` são conveniências locais, não defaults vazios do código.

## Imagens locais e S3

| Variável | Default | Uso |
| --- | --- | --- |
| `STORAGE_BACKEND` | `local` | `local` ou `s3` |
| `S3_ENDPOINT_URL` | Vazio | Endpoint compatível; vazio utiliza o endpoint padrão do SDK |
| `S3_REGION` | `us-east-1` | Região do cliente |
| `S3_BUCKET` | Vazio | Bucket de avatares e capas |
| `S3_ACCESS_KEY_ID` | Vazio | Credencial explicitamente fornecida |
| `S3_SECRET_ACCESS_KEY` | Vazio | Segredo correspondente |
| `S3_PUBLIC_BASE_URL` | Vazio | URL HTTPS pública para resolução das imagens |
| `S3_PREFIX` | `criticard` | Prefixo simples, podendo conter pastas separadas por `/` |

O backend S3 exige bucket, ambas as credenciais e URL pública HTTPS. O código passa credenciais ao SDK explicitamente, evitando usar por acidente perfis locais ou metadados da infraestrutura. A validação inicial não contata o bucket.

Os objetos são separados em prefixos para avatares e capas. Imagens têm nomes únicos e cache público imutável no S3. A política de leitura pública/CDN e as permissões de gravação/remoção são responsabilidade do ambiente.

Uma cópia local existente tem prioridade na resolução da URL. Mudar `STORAGE_BACKEND` não transfere arquivos antigos automaticamente. Emails, bancos, exports e pedidos privados não devem ser colocados nesse armazenamento público.

## Privacidade

| Variável | Default | Uso |
| --- | --- | --- |
| `PRIVACY_CONTROLLER_NAME` | `Luis Duarte` | Identificação apresentada em `/privacidade` |
| `PRIVACY_CONTACT_EMAIL` | Vazio | Canal externo apresentado quando configurado |

Esses campos alimentam o aviso da interface; configurar o nome não comprova atendimento de obrigações legais. O canal externo deve ser definido pelo responsável antes de disponibilizar o produto publicamente. Veja [Privacidade e exclusão](privacy-operations.md).

## Valores de aplicação, fora do `.env`

Os itens abaixo são defaults de `app.config` ou fallbacks internos. A configuração atual **não os lê automaticamente do ambiente**. Testes e integrações podem sobrescrevê-los por um dicionário em `create_app`; acrescentar uma variável ao `.env` com esse nome não basta.

| Opção | Valor padrão |
| --- | --- |
| `SESSION_COOKIE_HTTPONLY` | `True` |
| `SESSION_COOKIE_SAMESITE` | `Lax` |
| `MAX_CONTENT_LENGTH` | 3 MiB + 64 KiB para envelope do formulário |
| `MAX_FORM_MEMORY_SIZE` | 64 KiB |
| `MAX_FORM_PARTS` | 24 |
| `LOGIN_ATTEMPT_LIMIT` / `LOGIN_ATTEMPT_WINDOW` | 10 / 300 segundos |
| `REGISTER_ATTEMPT_LIMIT` / `REGISTER_ATTEMPT_WINDOW` | 5 / 900 segundos |
| `SETTINGS_SECURITY_ATTEMPT_LIMIT` / `SETTINGS_SECURITY_ATTEMPT_WINDOW` | 10 / 300 segundos |
| `PRIVACY_REQUEST_ATTEMPT_LIMIT` / `PRIVACY_REQUEST_ATTEMPT_WINDOW` | 10 / 300 segundos |
| `PRIVACY_ADMIN_ATTEMPT_LIMIT` / `PRIVACY_ADMIN_ATTEMPT_WINDOW` | 30 / 300 segundos |
| `COMMUNITY_WRITE_ATTEMPT_LIMIT` / `COMMUNITY_WRITE_ATTEMPT_WINDOW` | 20 / 300 segundos |
| `CHAT_RATE_LIMIT` / `CHAT_RATE_WINDOW` | 30 envios / 60 segundos |
| `ACCOUNT_RATE_WINDOW` | 900 segundos |
| `RESET_IP_LIMIT` / `RESET_EMAIL_LIMIT` | 5 / 3 |
| `VERIFY_IP_LIMIT` / `VERIFY_EMAIL_LIMIT` | 10 / 3 |
| `RESET_TOKEN_TTL_SECONDS` | 1800 segundos |
| `VERIFY_TOKEN_TTL_SECONDS` | 86400 segundos |

O limite de arquivo de imagem é 3 MiB e o limite de dimensão é 16 milhões de pixels em `uploads.py`; o acréscimo no limite da requisição não autoriza uma imagem maior.

Preferências de produto, como visibilidade inicial privada do backlog, estão em [settings/schema.py](../criticard/settings/schema.py). Elas são persistidas por pessoa e não configuradas no `.env`.

## Exigências do modo de produção

Quando `ENVIRONMENT=production`, a factory recusa iniciar sem:

- `SECRET_KEY` explícita com pelo menos 32 caracteres.
- `DATABASE_URL` PostgreSQL.
- Debug desativado, cookie seguro e `TRUSTED_HOSTS` explícitos.
- `ACCOUNT_BASE_URL` HTTPS válida.
- Backend SMTP, host, remetente e TLS `starttls` ou `ssl`.

Isso não configura um proxy TLS, provedor SMTP ou bucket: essas dependências precisam existir e ser verificadas. Para gerar um segredo novo:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Use um segredo persistente para todos os processos da mesma instalação e guarde-o fora do repositório. Alterá-lo invalida assinaturas de sessão e modifica as chaves dos budgets de tentativas.

## Compose e ferramentas

[`compose.yaml`](../compose.yaml) usa `.env.production` para os containers. `docker compose --env-file .env.production ...` também fornece valores para a interpolação do arquivo Compose.

| Variável de ferramenta | Onde atua |
| --- | --- |
| `POSTGRES_PASSWORD` | Credencial do serviço PostgreSQL no Compose; não é lida diretamente pelo Flask |
| `HEALTHCHECK_HOST` | Header `Host` do healthcheck interno; deve ser permitido em `TRUSTED_HOSTS` |
| `CRITICARD_TEST_POSTGRES_URL` | Opt-in dos testes que criam bancos PostgreSQL descartáveis |
| `CRITICARD_PG_BIN` | Diretório opcional dos clientes `pg_dump`/`pg_restore` nos testes de restauração; tem prioridade sobre runtime portátil e PATH |
| `CRITICARD_BROWSER_TESTS` | Valor `1` habilita testes Playwright |
| `PLAYWRIGHT_CHANNEL` | Seleciona navegador/canal para fixtures de navegador |

`.env.production.example` contém domínios ilustrativos e campos de segredo vazios. Não é uma configuração pronta de hospedagem. Consulte [Operação](operations.md) para ordem de migração, worker e proxy.
