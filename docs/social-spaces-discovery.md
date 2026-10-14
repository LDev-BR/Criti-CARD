# Descoberta, follows e espaços sociais

O Criti-CARD possui três experiências complementares: descoberta em `/feed`, críticas em `/criticas` e espaços de convivência em comunidades/chats. Elas compartilham identidade e regras de segurança, mas não o mesmo conteúdo ou associação.

## Mapa dos espaços

| Área | Conteúdo | Modelo de participação |
| --- | --- | --- |
| Descoberta | Tendências e recortes de interesse | Público, personalizado para conta autenticada |
| Feed de críticas | Cards de avaliação publicados | Leitura pública; publicação e interação autenticadas |
| Comunidades temáticas | Posts, comentários e reações | Membros, proprietário e moderadores |
| Chat direto | Mensagens entre duas pessoas | Participantes da conversa |
| Chat em grupo | Histórico e mensagens em tempo real | Membros, proprietário e moderadores |

Seguir uma obra não inclui automaticamente em comunidade ou grupo. Uma comunidade de livros não é uma conversa em grupo de livros; os fluxos de criação, convite e saída são separados.

## Hub de descoberta

[discovery/service.py](../criticard/discovery/service.py) calcula um contexto limitado para `/feed`, com até oito obras em tendência e recomendações de comunidades abertas. Para conta autenticada, apresenta ainda obras, categorias e autores seguidos, novas obras nas categorias acompanhadas e recorte de críticas.

Tendências consideram uma janela de sete dias. A pontuação por obra é:

```text
4 × críticas recentes
+ 2 × autores distintos dessas críticas
+ pessoas distintas que curtiram recentemente
+ 2 × pessoas distintas que comentaram recentemente
```

Uma obra precisa estar ativa e possuir crítica recente para aparecer. Cards arquivados e contas inativas não alimentam esses indicadores. Bloqueios do visitante autenticado também filtram autores e participantes considerados.

O algoritmo é uma soma determinística de atividade recente. Ele não consulta um serviço externo de recomendação nem perfila uma pessoa por aprendizado de máquina.

## Follows e feed de seguidos

| Relação | Mutação |
| --- | --- |
| Pessoa | `/users/<id>/follow` ou formulário de `/conexoes/<id>/seguir` |
| Obra | `/works/<id>/follow` |
| Categoria | `/categories/<id>/follow` |

As relações possuem unicidade por pessoa/alvo e mutações autenticadas com CSRF. Obra retirada não deve virar um novo interesse disponível no catálogo; a descoberta filtra obras ativas.

`/criticas?feed=following` combina, por união, cards de autores seguidos, obras seguidas e categorias seguidas. Não exige que as três condições sejam verdadeiras. Visitante sem login é encaminhado à entrada.

Os parâmetros são `q`, `categoria`, `obra`, `nota_min`, `ordem`, `feed` e `preferencias`. Selecionar uma obra compatível pode preencher sua categoria; valores inválidos são normalizados para uma seleção permitida.

Ordenação `popular`, apresentada como “Mais comentadas”, considera cards recentes e pontuação de duas vezes as curtidas mais três vezes os comentários. Ela é diferente do cálculo de tendências agregadas por obra do hub.

## Amizade e bloqueio

Amizade possui uma solicitação única por par ordenado de pessoas, com estado pendente ou aceito. Seguir é uma relação unilateral independente. As ações de amizade são pedir, aceitar, recusar, cancelar e remover.

Política de pedidos é verificada no servidor; `following` exige que o destinatário siga o solicitante. Bloquear remove relações incompatíveis e impede novos contatos conforme regras das áreas. Consulte [Privacidade](privacy-operations.md) para os limites do bloqueio em conteúdo público.

## Comunidades temáticas

Rotas são registradas com prefixo `/comunidades`. A listagem e páginas de comunidades abertas podem ser visitadas publicamente. A criação exige conta e sete dias desde a primeira contribuição válida; ela não exige nível 6 nem três dias de cota.

Comunidades possuem nome, descrição, categoria opcional, modo `open`/`closed`, nível mínimo, tema, ícone e capa opcional. Temas/ícones são tokens permitidos, sem CSS arbitrário. Nível configurável fica entre 1 e 999.

As migrações fornecem comunidades temáticas iniciais para as categorias. Criar e participar de comunidades não altera as revisões nem o catálogo congelado dessas migrações.

## Entrada em comunidade

| Ação | Caminho principal |
| --- | --- |
| Entrada direta em aberta | `POST /comunidades/<slug>/entrar` |
| Pedir entrada em fechada | `POST /comunidades/<slug>/solicitar` |
| Cancelar pedido | `POST /comunidades/solicitacoes/<id>/cancelar` |
| Responder pedido | `POST /comunidades/solicitacoes/<id>/<action>` |
| Convidar | `POST /comunidades/<slug>/convidar` |
| Responder convite | `POST /comunidades/convites/<id>/<action>` |
| Sair | `POST /comunidades/<slug>/sair` |

O nível mínimo é conferido na entrada e novamente em aceite/aprovação. Conhecer convite ou solicitação não concede acesso a uma terceira conta. Bloqueios são verificados nas interações entre as pessoas envolvidas.

Uma comunidade fechada mostra uma apresentação restrita para não membros: não entrega lista de posts/membros, descrição interna, capa nem contagem interna na página de detalhe. Conhecer ID de post também não contorna associação.

## Publicações e moderação

Membros podem publicar e comentar. Posts aceitam título de 1 a 120 caracteres e corpo de 1 a 5000. Uma obra opcional precisa estar ativa e pertencer à categoria da comunidade quando ela restringe categoria.

Reações permitidas são `like`, `insightful` e `fun`. Posts/comentários possuem autoria própria; edição e exclusão seguem permissões de autor e moderação. Denúncias suportam `community_post` e `community_comment` com verificação de visibilidade do alvo.

Papéis são `owner`, `moderator` e `member`. Moderação pode cuidar de entrada, participantes, configuração e conteúdo conforme o serviço; mudanças de papel que alteram administração são protegidas por regras específicas.

Ao sair o proprietário, a comunidade busca sucessor ativo, priorizando moderador e antiguidade. Sem sucessor, arquiva o espaço e libera a capa para limpeza. Exclusão de conta também trata essa sucessão antes de remover suas relações.

## Chats diretos

`/mensagens` lista apenas conversas do titular. `/mensagens/iniciar` aceita pessoa alvo e reutiliza uma conversa existente para o par; não cria uma nova conversa a cada envio.

Novos envios obedecem à política de recebimento atual do destinatário e a bloqueios. Participante pode conservar histórico quando a preferência muda, mas um bloqueio restringe acesso/entrega da conversa correspondente.

Não membros recebem erro ao consultar detalhe/histórico. A preferência de mensagens diretas não substitui a associação e os papéis de chats em grupo.

## Chats em grupo

`/mensagens/grupos` oferece descoberta autenticada e apresenta elegibilidade de criação. Grupos têm nome, descrição, modo, nível mínimo e identidade visual permitida.

Chat aberto exige nível 3 e 24 horas desde primeira contribuição. Chat fechado e criação exigem nível 6, 48 horas e três dias distintos de cota completa. Os detalhes de XP e as condições são definidos em [Progressão](progression.md).

| Ação | Caminho principal |
| --- | --- |
| Criar | `POST /mensagens/grupos/criar` |
| Entrar em aberto | `POST /mensagens/grupos/<id>/entrar` |
| Pedir acesso a fechado | `POST /mensagens/grupos/<id>/solicitar` |
| Aceitar/recusar convite | `POST /mensagens/grupos/convites/<id>/aceitar` ou `/recusar` |
| Responder pedido | `POST /mensagens/grupos/solicitacoes/<id>` |
| Sair | `POST /mensagens/grupos/<id>/sair` |
| Configurar | `POST /mensagens/grupos/<id>/configurar` |

Associação é revalidada no histórico, envio e entrega. Entrada considera conflitos com pessoas bloqueadas no grupo. Proprietário/moderadores controlam participantes; só o proprietário altera papéis de moderador/membro.

Saída do proprietário transfere o papel a moderador disponível ou membro mais antigo; sem sucessor, arquiva o grupo. Remoção de participante cancela solicitações/convites pendentes relacionados.

## Transporte e consistência do chat

O namespace Socket.IO é `/chat`, com eventos `join`, `send_message` e `mark_read`. Conexão exige sessão atual, origem compatível e CSRF. O servidor revalida identidade nos eventos e associação de destinatários na entrega.

Envio recebe corpo de até 2000 caracteres e `client_nonce` UUID. Unicidade por remetente/conversa/nonce evita duplicação quando uma resposta se perde e a mesma mensagem é repetida. Uma mensagem nova deve ter nonce novo.

Histórico HTTP em `/mensagens/<id>/historico` suporta cursores `before_id` e `after_id`; o cliente combina recuperação e eventos por IDs estáveis. `POST /mensagens/<id>/lida` atualiza leitura sem confiar em um contador enviado pelo navegador.

Formulários tradicionais permitem envio sem JavaScript. O registro de sockets é local ao processo; operação com múltiplos workers não é uma capacidade configurada. Veja [Operação](operations.md).

## Referências de manutenção

As fontes principais são `discovery/`, `social/`, `communities/`, `chat/` e `progression/access.py`. Testes de acesso devem incluir membro, não membro, outra conta, bloqueio, convite de terceiro, sessão revogada e concorrência quando a regra usa locks.
