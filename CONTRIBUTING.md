# Contribuindo com o Criti-CARD

Contribuições podem melhorar código, testes, acessibilidade, documentação e exemplos. Comece por [README](README.md), [Primeiros passos](docs/getting-started.md) e pelas instruções de [AGENTS.md](AGENTS.md).

## Preparar o ambiente

Use Python 3.11+ (recomendado 3.13), ambiente virtual e as dependências de desenvolvimento. Para ferramentas JavaScript, use Node 22+ e instale pelo lockfile.

```bash
python -m pip install -r requirements-dev.txt
npm ci --ignore-scripts
```

Uma configuração de teste deve usar banco e pastas temporários. Seu banco pessoal de desenvolvimento não é uma fixture. Não aponte uma suíte para `criticard.db`, `instance/criticard.db` ou PostgreSQL publicado.

## Propor uma alteração

Para bugs, descreva a ação, o resultado observado, o esperado e os passos de reprodução. Inclua ambiente relevante, como navegador e versão Python, usando contas e dados fictícios.

Para uma funcionalidade, explique a necessidade e o comportamento proposto, incluindo permissões e alternativas de interface quando pertinentes. Mudanças amplas devem ter limites claros para facilitar revisão.

Use uma branch própria e preserve mudanças locais de outras tarefas. Mantenha commits relacionados ao objetivo e evite incluir bancos, uploads, caches, segredos ou artefatos do seu ambiente.

## Organização do código

- Siga o padrão da funcionalidade existente em `criticard/`.
- Quando existe serviço, mantenha nele autorização e regras de negócio; rotas cuidam de HTTP e templates de apresentação.
- Use expressões SQLAlchemy e parâmetros; não monte SQL com entrada de usuário.
- Mantenha transações com limites explícitos, sem commit escondido em auxiliares que participam de uma ação maior.
- Ao criar tabelas, use a metadata compartilhada e preserve SQLite/PostgreSQL.
- Não confunda `/feed` com `/criticas`, nem comunidades com chats em grupo.

Leia [Arquitetura](docs/architecture.md) para a factory, wrapper de persistência e mapa dos módulos.

## Autorização e privacidade

Verifique identidade, autoria, associação, bloqueios e papéis no servidor em toda consulta privada e mutação. Preserve CSRF nos formulários/JSON e a autenticação independente dos eventos Socket.IO.

Não use campos enviados pelo cliente como fonte de XP, privilégio, titular da consulta ou contador. Ações sensíveis devem preservar a revalidação de sessão e os locks existentes.

Uma alteração de visibilidade precisa considerar tanto conteúdo quanto contagens, previews, descoberta, export e notificações. [Privacidade](docs/privacy-operations.md) e [Espaços sociais](docs/social-spaces-discovery.md) descrevem os limites atuais.

## Esquema e migrações

Crie uma nova revisão Alembic para alterar o esquema. Não edite uma revisão já aplicada para corrigir uma instalação futura, nem use remoção de dados reais como estratégia de teste.

Verifique preservação de dados, constraints, índices e os dois bancos suportados. Mudanças de unicidade precisam exercitar a migração de dados anteriores e a escrita concorrente no destino PostgreSQL quando pertinente.

Seeds históricos de migrações são congelados. Alterar o catálogo de produto deve usar o fluxo adequado ou nova migração, considerando importação e a validação estrita do destino vazio.

## Interface

Preserve HTML semântico, labels, foco, teclado, responsividade e os fallbacks sem JavaScript. Prefira os assets locais e os tokens existentes; não introduza dependência externa de fonte, ícone ou capa sem justificativa.

Feedback deve mostrar a ação real e estados de erro/espera. Não exponha detalhes de infraestrutura em fluxos do produto quando não ajudarem a pessoa a decidir.

Ao alterar conexões, consulte [Referência visual](docs/design/connections-visual.md). Assets adicionados precisam ter origem e licença adequadas documentadas.

## Testes antes de enviar

```bash
python -m pytest -q
npm test
```

Comece pelos testes do domínio e amplie em mudanças transversais, de autenticação, privacidade ou esquema. Acrescente regressões junto à funcionalidade quando houver comportamento a proteger; evite testes que apenas repitam linhas da implementação.

Testes de navegador e PostgreSQL são opcionais localmente e possuem instruções em [Testes](docs/testing.md). Quando não forem executados, informe isso na descrição. Não trate um teste ignorado como uma verificação aprovada.

## Documentação e arquivos públicos

Atualize o guia da área quando mudar rota, regra, CLI ou configuração. Exemplos devem ser reproduzíveis e preservar a diferença entre valores padrão, sugestões locais e exigências de produção.

O `.gitignore` exclui arquivos de ambiente, bancos, backups, uploads, outbox e exports pessoais no padrão `criticard-dados-*.json`; `.dockerignore` também evita incluir esses arquivos no contexto da imagem. Ignore não é proteção de acesso: confira o conteúdo antes de commit e use dados fictícios nas capturas.

Não inclua URL de implantação, badge de sucesso ou estatística de testes sem evidência. Use links relativos e mantenha a origem de capturas/assets pública e verificável.

## Descrição do pull request

Explique o problema concreto e o comportamento após a mudança. Acrescente apenas detalhes de implementação que ajudem a revisão, incluindo migração, permissão ou compatibilidade quando afetadas.

Informe comandos de verificação e resultados observados, testes opcionais não executados e uma limitação material. Para interface, apresente capturas fictícias quando ajudarem a avaliar estados e responsividade.

Antes de enviar, confira o diff para remover dados privados, alterações de execução e arquivos sem relação. O workflow de CI valida a versão enviada; ele não publica automaticamente o produto.

## Segurança e licenças

Vulnerabilidades seguem [SECURITY.md](SECURITY.md) e devem ser comunicadas de forma privada. Não publique tokens, credenciais ou exploração de contas reais em uma issue.

O código possui [licença MIT](LICENSE). Fontes e cliente Socket.IO mantêm seus avisos próprios em `static/`; preserve esses arquivos ao redistribuir ou atualizar dependências locais.
