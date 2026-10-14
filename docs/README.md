# Documentação do Criti-CARD

O Criti-CARD reúne críticas de obras culturais, organização de uma coleção pessoal e espaços de convivência. A aplicação usa Flask, templates Jinja, SQLAlchemy e JavaScript próprio; SQLite atende ao desenvolvimento e PostgreSQL é o banco exigido pelo modo de produção.

Estes guias descrevem o comportamento presente no repositório. Capturas e exemplos usam dados fictícios. Uma configuração ou um arquivo de implantação disponível no código não significa que exista uma instância pública em operação.

## Por onde começar

| Objetivo | Guia |
| --- | --- |
| Conhecer o projeto e suas capturas | [README principal](../README.md) |
| Executar a aplicação localmente | [Primeiros passos](getting-started.md) |
| Entender módulos, persistência e decisões | [Arquitetura](architecture.md) |
| Explorar as funcionalidades e rotas | [Funcionalidades](features.md) |
| Configurar banco, email, imagens e produção | [Configuração](configuration.md) |
| Executar verificações e entender a CI | [Testes](testing.md) |
| Aplicar migrações, fazer backup e operar containers | [Operação](operations.md) |
| Preparar e apresentar o repositório no GitHub | [Publicação do portfólio](github-portfolio.md) |
| Contribuir com código ou documentação | [CONTRIBUTING](../CONTRIBUTING.md) |
| Comunicar uma vulnerabilidade | [SECURITY](../SECURITY.md) |

## Referências por domínio

| Área | Conteúdo |
| --- | --- |
| [Descoberta e espaços sociais](social-spaces-discovery.md) | Hub, follows, comunidades temáticas, grupos e limites de acesso |
| [Jornada e progressão](progression.md) | XP, cotas, níveis, conquistas e importação histórica |
| [Notificações](notifications.md) | Caixa pessoal, contador, filtros e ações de leitura |
| [Catálogo administrativo](admin-catalog.md) | Obras, capas, validação, retirada e reativação |
| [Privacidade e exclusão](privacy-operations.md) | Visibilidade, exportação, pedidos e ciclo de exclusão |
| [Interface de conexões](design/connections-visual.md) | Composição, comportamento, acessibilidade e arquivos da tela |

## Vocabulário do projeto

**Obra** é um item do catálogo compartilhado. **Card** é a crítica de uma pessoa sobre uma obra, com texto e nota. **Backlog** é a entrada individual que organiza o consumo da obra; sua visibilidade é independente da publicação de uma crítica.

**Comunidade temática** é um espaço de publicações, comentários e reações. **Chat em grupo** é uma conversa com mensagens em tempo real. Os dois possuem modelos, associações e fluxos de entrada separados.

**Seguir** uma pessoa acompanha suas críticas. **Amizade** depende de solicitação e aceite. Seguir obras e categorias alimenta a descoberta; essas relações não concedem, por si, acesso a mensagens ou conteúdo privado.

## Rotas que orientam a navegação

| Caminho | Papel |
| --- | --- |
| `/` | Login e entrada da conta |
| `/feed` | Descoberta de obras, autores e comunidades |
| `/criticas` | Feed de críticas com filtros |
| `/dashboard` | Painel da própria conta |
| `/catalogo` | Catálogo público |
| `/backlog` | Coleção completa da pessoa autenticada |
| `/comunidades/` | Comunidades temáticas |
| `/mensagens` | Conversas da própria pessoa |
| `/conexoes` | Amizades, follows e busca de pessoas |
| `/jornada` | Extrato e recompensas pessoais |
| `/configuracoes` | Preferências e segurança da conta |

## Como manter estes guias

Ao alterar uma regra de negócio, atualize o guia do domínio e seus testes. Mudanças de variáveis de ambiente devem chegar também a `.env.example`; comandos operacionais devem corresponder às opções registradas no CLI.

Documente limitações observadas sem prometer capacidade, disponibilidade ou conformidade não verificadas. Preserve links relativos para que a documentação funcione no GitHub e em uma cópia local. Instruções do repositório estão em [AGENTS.md](../AGENTS.md).
