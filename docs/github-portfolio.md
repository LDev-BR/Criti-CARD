# Apresentação e publicação no GitHub

Este guia trata da publicação do código como portfólio. Para colocar a aplicação em funcionamento em um servidor, consulte [Operação](operations.md) e [Configuração](configuration.md).

## O que uma pessoa pode avaliar

O [README principal](../README.md) apresenta o produto, seis capturas reais com dados fictícios, funcionalidades, stack, execução local e links para os detalhes. A documentação permite seguir uma regra da interface até os serviços e testes correspondentes.

Uma sequência útil para revisão técnica:

1. Execute a aplicação seguindo [Primeiros passos](getting-started.md).
2. Visite descoberta, críticas, catálogo e perfil; crie uma conta local para experimentar backlog e publicação.
3. Leia [Arquitetura](architecture.md) para localizar factory, blueprints, serviços, modelos e transações.
4. Escolha uma área em [Funcionalidades](features.md) e consulte seu guia e seus testes.
5. Execute as verificações em [Testes](testing.md), distinguindo aprovação de testes ignorados por falta de integrações opcionais.

As contas e o conteúdo das capturas não são seeds de uma instalação comum. O [gerador de capturas](screenshots/README.md) prepara esses dados apenas em um banco temporário.

## Arquivos públicos e privados

O código, templates, assets próprios, migrações, testes, exemplos de configuração, licenças e workflows pertencem ao repositório. Node e o runtime Python do workspace não são distribuídos; as dependências são instaladas pelos arquivos de requisitos e pelo lockfile.

O [`.gitignore`](../.gitignore) exclui ambientes, credenciais, bancos, backups, uploads de pessoas, caixa de saída de email, resultados de testes e estado de infraestrutura. Os exemplos permitidos são `.env.example` e `.env.production.example`; ambos devem continuar sem segredos reais. Exportações pessoais com o nome usado pelo app, `criticard-dados-*.json`, também são excluídas.

As capturas públicas ficam em `docs/screenshots/` e as ilustrações do catálogo em `static/catalog/`. Essas pastas são versionadas. `static/uploads/` e `static/cards/` guardam arquivos enviados e ficam fora do Git. Não ignore todas as imagens: isso removeria a apresentação e os assets necessários ao funcionamento.

O [`.dockerignore`](../.dockerignore) também exclui os arquivos privados do contexto de construção da imagem. As regras de Git e Docker têm finalidades distintas e precisam ser mantidas ao introduzir novos arquivos locais.

## Conferir antes de um commit

Na raiz do projeto:

```bash
git status --short
git check-ignore -v -- .env criticard.db instance/secret_key static/uploads/exemplo.png criticard-dados-1.json
git add -A
git diff --cached --name-only
git diff --cached --stat
git diff --cached --check
```

Revise os caminhos e o conteúdo das mudanças antes de confirmar. As regras de exclusão não removem um arquivo já rastreado nem apagariam versões antigas do histórico. Uma credencial exposta precisa ser revogada; simplesmente ignorar seu nome depois não resolve a exposição.

Não use `git add -f` para incluir bancos, uploads ou arquivos de configuração privados. Para reproduzir um problema, use fixtures e conteúdo fictício.

O [`.gitattributes`](../.gitattributes) padroniza arquivos de código/documentação com LF, scripts PowerShell com CRLF e trata fontes e imagens como binários. Ele ajuda a evitar diferenças de fim de linha entre contribuições Linux e Windows.

## Enviar o código

Confira o destino configurado:

```bash
git remote -v
git log -1 --oneline
git status --short
```

Quando a revisão local e os testes estiverem concluídos, envie a branch escolhida ao seu repositório. Para este projeto, a branch principal é `main`:

```bash
git push -u origin main
```

Esse comando é uma ação separada da preparação local. Ele precisa de autenticação do proprietário e publica os commits no remoto configurado; não faz implantação da aplicação.

## Primeira execução do CI

O [workflow](../.github/workflows/ci.yml) roda em pushes para `main`/`master`, pull requests e acionamento manual. Após o envio, confira os jobs Python, JavaScript, PostgreSQL e navegador na aba Actions. A configuração local validada não equivale a uma execução hospedada aprovada.

O badge do README usa `LDev-BR/Criti-CARD`. Se copiar o projeto para outro proprietário ou mudar seu nome, atualize os dois links do badge. Uma falha deve ser investigada pelo log e pelo relatório do job correspondente, sem incluir tokens ou dados pessoais em issues.

O workflow usa valores públicos de teste e serviços descartáveis. Não cadastre credenciais de produção para tentar fazer os testes passar. Dependabot propõe atualizações das Actions; revise essas mudanças e seus resultados antes de incorporá-las.

## Apresentação do portfólio

Uma descrição curta adequada para o campo About:

> Rede social de críticas culturais com Flask, PostgreSQL, comunidades, chat em tempo real e testes automatizados.

Sugestões de tópicos: `flask`, `python`, `sqlalchemy`, `postgresql`, `socketio`, `jinja2`, `pytest` e `portfolio`.

Mantenha a descrição coerente com o código. Acrescente um link de demonstração somente quando existir uma instalação acessível e revisada. As imagens fictícias do README não afirmam disponibilidade de um serviço público.

As [licenças dos assets](../README.md#licenças-e-assets), [orientações de contribuição](../CONTRIBUTING.md) e [segurança](../SECURITY.md) completam as informações úteis para quem clona ou revisa o projeto.
