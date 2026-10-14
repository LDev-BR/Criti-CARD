# Operação, migrações e publicação

Este guia trata dos comandos e arquivos existentes no repositório. O ambiente local usa SQLite; o modo `production` exige PostgreSQL, HTTPS e SMTP seguro. Não há um endereço público de implantação declarado aqui.

## Ordem de inicialização

1. Instale dependências e configure banco, segredo, host público e email.
2. Confirme qual banco a configuração seleciona.
3. Faça backup e valide a restauração antes de atualizar uma instalação com dados.
4. Execute migrações com a versão de código que será iniciada.
5. Inicie processo web e worker usando a mesma configuração.
6. Verifique páginas públicas, login, persistência, imagens, recuperação e entrega de chat.

Fora dos testes, importar `app.py` não aplica migrações. Essa separação evita que cada worker tente alterar o esquema ao subir.

## Comandos da aplicação

Com o ambiente Python ativo e na raiz:

```bash
python -m flask --app criticard db-upgrade
python -m flask --app criticard init-db
python -m flask --app criticard db-backup backups/criticard-local.db
python -m flask --app criticard db-import-sqlite backups/criticard-local.db --confirm-empty-target --dry-run
python -m flask --app criticard progression-import-history --dry-run
python -m flask --app criticard privacy-cleanup-images --limit 100
python -m flask --app criticard accounts-send-mail --limit 50
```

Cada linha representa uma operação independente. `init-db` e `db-upgrade` têm o mesmo efeito de atualização; não é necessário executar ambos. O comando de importação só aceita um destino PostgreSQL vazio sob as regras abaixo.

No PowerShell, substitua `python` por `.\.venv\Scripts\python.exe`, ou pelo runtime local documentado em [Primeiros passos](getting-started.md).

## Migrações e atualização

Alembic recebe uma conexão da engine e aplica `heads`. Dados existentes são preservados pelas revisões; novas mudanças de esquema exigem uma nova revisão em `migrations/versions/`.

Antes de uma atualização com dados, mantenha uma cópia do banco e dos arquivos enviados, registre a revisão de código em uso e pare escritas quando o plano de manutenção exigir consistência entre banco e arquivos. Não edite revisões já aplicadas para alterar o comportamento futuro.

Na introdução da crítica única, a migração arquiva duplicatas históricas e conserva a mais recente por padrão. Importação histórica de XP é um comando separado e explícito; a migração de esquema não inventa atividade anterior.

O projeto não oferece um comando genérico de rollback de publicação. Uma reversão deve considerar a compatibilidade entre código, esquema e dados; restaure uma cópia verificada quando for esse o procedimento escolhido.

## Backup SQLite

`db-backup DESTINATION` usa a API de backup do SQLite para produzir uma cópia consistente. Recusa um arquivo de destino já existente e não funciona para PostgreSQL.

```bash
python -m flask --app criticard db-backup backups/criticard-antes-da-atualizacao.db
```

O arquivo de banco não inclui uploads, capas personalizadas nem caixa de saída. Faça cópias separadas desses diretórios quando forem necessários à restauração. Backups contêm dados pessoais e credenciais com hash; mantenha acesso restrito e retenção definida pelo responsável.

Para conferir uma cópia SQLite sem tocar a instalação, abra o arquivo restaurado em um ambiente isolado, execute `PRAGMA integrity_check` e `PRAGMA foreign_key_check`, aplique migrações nessa cópia e visite os fluxos relevantes.

## Backup e restauração PostgreSQL

Use os utilitários PostgreSQL compatíveis com o servidor. Um formato custom permite restauração por `pg_restore`:

```bash
pg_dump --format=custom --file=backups/criticard.dump --dbname=criticard
pg_restore --exit-on-error --dbname=criticard_restore_check backups/criticard.dump
```

Esses exemplos pressupõem conexão configurada por mecanismos do cliente, como host, usuário e arquivo de senha. O banco de verificação deve ser criado separadamente e não conter a instalação ativa. Não grave senha literal em scripts versionados ou logs.

Valide contagens, relacionamentos, migrações e leitura da aplicação no banco restaurado. Testes específicos de restauração estão em `tests/test_postgres_restore.py`; execução bem-sucedida de `pg_dump` sozinha não prova recuperabilidade da instalação completa.

## Transferência SQLite → PostgreSQL

`db-import-sqlite SOURCE --confirm-empty-target [--dry-run]` é uma transferência de banco para uma instalação nova, não uma sincronização nem uma mesclagem de contas.

O processo em [transfer.py](../criticard/transfer.py):

- Abre a origem somente para leitura, faz backup e migra uma cópia temporária.
- Verifica foreign keys da cópia e compatibilidade de tabelas, colunas e revisão Alembic.
- Bloqueia tabelas do destino para impedir escrita concorrente durante validação/cópia.
- Aceita ausência de dados ou apenas os seeds originais intactos de catálogo/comunidades.
- Copia em lotes, confere contagens e constraints, e reinicia sequências dentro da transação.
- Reverte tudo no `--dry-run` ou em falha; a origem continua inalterada.

Um catálogo personalizado, comunidades alteradas ou qualquer dado de aplicação no destino fazem a transferência ser recusada. A ausência de usuários não basta para declarar o destino vazio.

Procedimento:

1. Prepare um PostgreSQL novo, mantenha o app/worker parados e aponte `DATABASE_URL` para ele.
2. Deixe `ADM_USERNAME` e `ADM_SENHA` vazios durante o bootstrap do destino: criar administrador já constitui dado de aplicação.
3. Execute `db-upgrade` no destino.
4. Execute a simulação e confira o relatório.
5. Execute novamente sem `--dry-run` quando a conferência for satisfatória.
6. Transfira imagens separadamente, preservando os nomes e os caminhos configurados.
7. Verifique login, coleções, conversas, pedidos e novos inserts antes de liberar escrita.

```bash
python -m flask --app criticard db-upgrade
python -m flask --app criticard db-import-sqlite caminho/origem.db --confirm-empty-target --dry-run
python -m flask --app criticard db-import-sqlite caminho/origem.db --confirm-empty-target
```

Simulação é uma transação real que adquire locks, valida e faz rollback. Execute-a em janela adequada. A transferência não envia imagens ao S3 nem copia arquivos de email.

## Containers fornecidos

[Dockerfile](../Dockerfile) utiliza Python 3.13, instala dependências de produção e executa como usuário sem root. O comando padrão é Gunicorn com `gthread`, **um worker**, 32 threads e porta interna 8000.

[compose.yaml](../compose.yaml) inclui PostgreSQL 18, um serviço de migração que termina, o app e o worker de email. Banco saudável precede a migração; o app/worker aguardam migração concluída.

Para preparar uma instalação de demonstração própria:

```bash
cp .env.production.example .env.production
```

Preencha segredos, host público, SMTP e canal de privacidade. Depois:

```bash
docker compose --env-file .env.production config --quiet
docker compose --env-file .env.production up --build -d
docker compose --env-file .env.production ps
docker compose --env-file .env.production logs --tail 100 app mail-worker migrate
```

`config --quiet` valida sem imprimir a configuração expandida com segredos. O Compose usa volumes para PostgreSQL, avatares, capas e outbox, filesystem de aplicação somente leitura, `/tmp` temporário e restrição de capacidades.

O serviço web usa `expose: 8000`, sem mapear uma porta pública do host. O proxy ou a plataforma de publicação deve alcançar essa porta na rede apropriada. O healthcheck faz `GET /feed` usando `HEALTHCHECK_HOST`.

Parar com `docker compose ... down` preserva volumes por padrão. Remover volumes apaga dados persistentes e deve ser uma decisão explícita de manutenção.

## HTTPS e proxy

O proxy termina HTTPS, preserva `Host` e encaminha WebSocket e HTTP. `TRUSTED_HOSTS` deve listar os hosts efetivamente permitidos; `ACCOUNT_BASE_URL` precisa usar o endereço público correto, sem credenciais ou parâmetros extras.

`PROXY_HOPS` aplica confiança a IP e protocolo encaminhados. Configure o número real de proxies confiáveis, de zero a três, e restrinja acesso direto que permitiria forjar esses headers. A configuração cobre também o middleware Socket.IO.

O processo web possui um registro de sockets em memória. Não aumente workers nem réplicas esperando que o chat distribua eventos automaticamente: não há broker compartilhado configurado. Escala distribuída requer trabalho de arquitetura e testes próprios.

## Entrega de email

O processo HTTP cria arquivos privados; um worker entrega SMTP em lotes:

```bash
python -m criticard.accounts.worker --interval 30 --limit 50
```

O intervalo mínimo é dez segundos e o lote aceita 1 a 1000 mensagens. Para uma execução avulsa, use `accounts-send-mail --limit 50`.

Jobs são reivindicados por rename; falhas voltam à fila e reivindicações antigas são recuperadas após dez minutos. Tokens expirados ou invalidados são arquivados em `discarded/`, entregues em `sent/`. Uma falha após entrega externa e antes do arquivamento pode ocasionar reenvio; não há garantia de entrega única pelo transporte SMTP.

Web e worker precisam compartilhar o mesmo spool e banco. As pastas de mensagens enviadas/descartadas também contêm dados privados e não possuem uma rotina automática de retenção documentada; estabeleça limpeza operacional adequada.

## Imagens e limpeza

Armazenamento local precisa de volumes persistentes. S3 precisa de credenciais explícitas e base pública HTTPS; alterar o backend não transfere imagens antigas. As ilustrações do catálogo em `static/catalog/` fazem parte do código versionado.

Troca de imagem ou exclusão agenda remoção depois de confirmar os dados. Falhas ficam em `pending_image_deletions` e podem ser repetidas:

```bash
python -m flask --app criticard privacy-cleanup-images --limit 100
```

O comando verifica referências ainda existentes e pode remover cópias local/S3 do mesmo arquivo. [Privacidade e exclusão](privacy-operations.md) detalha o alcance e o que precisa ser tratado em backups.
