# Funcionalidades e fluxos

O produto organiza a descoberta e a conversa em torno de obras de jogos, filmes, séries, livros, animes e mangás. A experiência combina páginas públicas de leitura com áreas pessoais autenticadas.

## Mapa de acesso

| Página | Acesso | Finalidade |
| --- | --- | --- |
| `/feed` | Público, com contexto pessoal após login | Descoberta |
| `/criticas` | Público; filtro de seguidos exige login | Críticas publicadas |
| `/catalogo` | Público | Obras compartilhadas |
| `/perfil/<username>` | Público | Perfil e críticas visíveis |
| `/card/<id>` | Público para publicação; histórico restrito ao autor | Leitura de uma crítica |
| `/colecao/<username>` | Público para entradas públicas; titular vê suas entradas | Coleção selecionada |
| `/dashboard` | Conta autenticada | Perfil pessoal e críticas |
| `/backlog` | Conta autenticada | Coleção completa |
| `/conexoes` | Conta autenticada | Relações pessoais |
| `/mensagens` | Conta autenticada e participante nas conversas | Chat |
| `/jornada` | Conta autenticada | Progresso e recompensas |
| `/configuracoes` | Conta autenticada | Preferências e conta |
| `/admin`, `/admin/obras` | Administrador | Operação da comunidade e catálogo |

A exigência de login não é a única regra: serviços verificam autoria, associação, bloqueios, papéis e sessão atual antes das ações correspondentes.

## Cadastro e perfil

`/cadastro` valida identidade, email e senha. Campos de apresentação podem ser completados no perfil; imagem é opcional. Username e email são únicos e o login aceita ambos, sem distinção de maiúsculas/minúsculas na busca.

`/edit` permite atualizar os dados da própria conta e trocar avatar. Mudar o email limpa a verificação anterior e invalida links antigos. Imagens são validadas pelo conteúdo e regravadas pelo servidor.

O painel `/dashboard` apresenta críticas publicadas e histórico arquivado em abas. A mensagem à equipe em `/mensagem` é um canal de suporte autenticado separado dos pedidos privados de privacidade.

## Descoberta

`/feed` é a porta de descoberta, com obras em atividade recente e comunidades abertas recomendadas. Após login, inclui recortes dos autores, obras e categorias seguidos pela pessoa.

A pontuação de tendências considera apenas os últimos sete dias: quantidade de críticas, autores distintos, pessoas distintas que curtiram e pessoas distintas que comentaram. Obras retiradas e cards arquivados não entram nas tendências.

Leia [Descoberta e espaços sociais](social-spaces-discovery.md) para o cálculo e as fronteiras de visibilidade.

## Catálogo e crítica única

`/catalogo` permite procurar obras e navegar por categorias. A mesma obra é usada no backlog e na publicação de crítica; sua capa vem do catálogo, com ilustrações temáticas locais ou imagem definida pela administração.

Em `/cadastro_cards`, selecione uma obra, escreva a crítica e atribua nota inteira de 0 a 100. A interface oferece prévia e orientação de leitura. Para uma obra já avaliada, o fluxo encaminha à edição do card existente.

Só pode existir um card publicado por pessoa/obra. Essa regra é protegida no serviço e por índice único parcial no banco. Editar uma avaliação preserva a identidade do card; excluir e republicar não transforma a mesma obra em uma nova fonte de XP.

Cards antigos sem vínculo a uma obra podem permanecer legíveis. Duplicatas históricas arquivadas ficam disponíveis ao titular como histórico privado, sem voltar ao feed público.

## Feed de críticas

`/criticas` combina busca, categoria, obra, nota mínima, ordenação e origem do feed. As opções de ordenação são recentes, mais comentadas, maior nota, menor nota e mais antigos. O recorte de seguidos combina autores, obras e categorias seguidos.

Preferências pessoais oferecem valores iniciais. Parâmetros escolhidos na página têm prioridade e a opção `preferencias=ignorar` permite voltar a uma visão sem esses defaults. Paginação conserva os filtros selecionados.

Cards oferecem curtidas e comentários. Editar ou remover comentário depende de autoria e das regras de moderação, verificadas no servidor. Denúncias podem ser enviadas sobre alvos suportados e revisadas em `/moderation` por administradores.

## Backlog e coleção

O backlog guarda uma entrada por pessoa/obra. Os estados são `planned`, `in_progress`, `completed`, `paused` e `dropped`, com rótulos adaptados à categoria: jogar, assistir ou ler.

Progresso aceita inteiro de 0 a 100000 e unidade de horas, episódios ou capítulos. Estado e progresso são valores próprios; a aplicação não busca consumo automaticamente em plataformas externas.

Novas entradas usam visibilidade privada por padrão. A pessoa pode tornar cada entrada pública; `/colecao/<username>` filtra dados e contagens no servidor para mostrar apenas o conjunto permitido ao visitante.

As ações principais são `POST /backlog/add`, `POST /backlog/<id>/update` e `POST /backlog/<id>/remove`. Formulários e JSON passam pelas mesmas regras de propriedade.

## Conexões

`/conexoes` reúne amigos, solicitações recebidas/enviadas, seguindo, seguidores e descoberta de pessoas. Busca e paginação pertencem à aba atual. `/amigos` e `/solicitacoes` redirecionam às abas correspondentes.

Seguir é unilateral. Amizade usa pedido e aceite. Bloquear encerra as relações incompatíveis e interfere em interações e mensagens; desbloquear não recria automaticamente os vínculos anteriores.

Preferências permitem limitar pedidos de amizade e novas mensagens. A seção de bloqueados lista apenas bloqueios feitos pela própria pessoa. Veja [Privacidade](privacy-operations.md) e [Interface de conexões](design/connections-visual.md).

## Conversas e comunidades

Conversas diretas começam em `/mensagens/iniciar`. Os participantes têm histórico, mensagens com até 2000 caracteres e leitura acompanhada por conversa. Socket.IO melhora a entrega; histórico e envio também possuem caminhos HTTP.

Chats em grupo são descobertos em `/mensagens/grupos`. Podem ser abertos ou fechados, com papéis de proprietário, moderador e membro. Nível, tempo de participação e histórico de cota condicionam entrada e criação.

Comunidades em `/comunidades/` possuem publicações, comentários e reações `like`, `insightful` e `fun`. Uma publicação pode associar uma obra. Comunidades fechadas protegem seu conteúdo de visitantes sem associação.

Participar de uma comunidade não inclui uma pessoa em um chat em grupo. Os detalhes de entrada, convites e moderação estão em [Espaços sociais](social-spaces-discovery.md).

## Jornada e personalização

`/jornada` apresenta saldo de XP, nível, conquistas, recompensas e extrato. A política reconhece contribuições reais, atividade semanal e permanência; há limite diário de créditos de origem `live`.

Recompensas incluem títulos, molduras, acabamento dos cards e selos permitidos pelo catálogo. A exibição pública da jornada vem desativada por padrão e o extrato continua privado. Consulte os valores e os gates em [Progressão](progression.md).

## Preferências, notificações e conta

`/configuracoes` reúne aparência, feed, jornada, notificações, privacidade, chat, conta e bloqueados. Oferece temas, texto maior, alto contraste, redução de movimento, densidade, resumo e opções de leitura dos cards.

`/notifications` é a caixa pessoal de atividade, com filtros e ações de leitura. Seu contador é separado da quantidade de mensagens não lidas no chat. [Notificações](notifications.md) explica atualização e preferências.

A conta oferece troca de senha, encerramento de sessões, exportação JSON, recuperação e verificação de email. A exclusão exige senha atual e remove conteúdo autoral; pedidos privados possuem protocolo e resposta administrativa.

## Escopo da versão

O catálogo e a coleção são mantidos no próprio Criti-CARD. Não há integração automática de consumo, compra de conteúdo, pagamentos ou importação de bibliotecas externas documentada nesta versão.

Os guias descrevem recursos implementados. A configuração de produção e a CI fornecem meios de validar e operar o projeto; suas capacidades efetivas devem ser conferidas no ambiente em que ele for disponibilizado.
