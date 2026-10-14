# Notificações

A caixa de atividade é pessoal e persistida no banco. O contador do sino representa notificações não lidas; a quantidade de mensagens não lidas pertence ao chat e é calculada separadamente.

## Eventos apresentados

| Tipo | Evento | Preferência |
| --- | --- | --- |
| `like` | Curtida em um card do destinatário | `notify_likes` |
| `comment` | Novo comentário em card do destinatário | `notify_comments` |
| `follow` | Novo seguidor | `notify_follows` |
| `friend_request` | Solicitação de amizade | `notify_friend_requests` |
| `friend_accept` | Aceite de solicitação | `notify_friend_accepts` |

Essas preferências vêm ativadas. Elas controlam a geração dos eventos correspondentes, não apagam o histórico que já existe. Uma ação sobre conteúdo próprio não gera notificação para o próprio ator.

A apresentação também reconhece o tipo `message`, direcionando a `/mensagens`, quando esse registro existe. O fluxo atual de envio do chat usa seu próprio histórico/contador; não se deve inferir que cada mensagem cria uma linha na caixa social.

## Caixa pessoal

`GET /notifications` aceita:

| Parâmetro | Valores |
| --- | --- |
| `state` | `all`, `unread`, `read` |
| `kind` | `all` ou um tipo reconhecido |
| `page` | Inteiro positivo; páginas fora do resultado retornam erro |

Cada página contém até trinta eventos, ordenados do mais novo para o mais antigo. A rota pode renderizar HTML ou retornar JSON quando solicitado. Consulta usa sempre `recipient_id` da sessão; não recebe um destinatário arbitrário do cliente.

O snapshot do contador retorna `unread_count`, `latest_id` e `latest_at`. É uma consulta do estado atual, não um campo que o navegador possa gravar diretamente.

## Leitura e navegação

| Ação | Rota |
| --- | --- |
| Marcar um evento lido | `POST /notifications/<id>/read` |
| Marcar e abrir destino | `POST /notifications/<id>/open` |
| Marcar todos os eventos pessoais | `POST /notifications/read-all` |
| Consultar contador | `GET /notifications/unread-count` |

Mutações exigem CSRF e sessão atual revalidada após lock. Marcar novamente um evento já lido mantém o momento existente, sem fabricar um novo evento. `read-all` aplica ao conjunto do titular, não apenas ao filtro visível.

Links de destino são construídos pelo servidor: detalhe de card/comentário, perfil do seguidor, aba de amigos/solicitações ou caixa de mensagens. Se não houver destino adequado, abrir retorna à caixa. O acesso no destino continua passando por suas próprias regras.

## Idempotência

A chave de evento evita notificações repetidas por uma mesma curtida/follow entre as mesmas identidades. Remover e refazer a relação não deve gerar uma sequência ilimitada da mesma notificação. Comentários têm identidade própria, portanto comentários novos podem produzir eventos novos.

Eventos de amizade usam a identidade da solicitação e regras próprias em `social/connections.py`. Notificação participa da transação da ação social; não confirma o banco antecipadamente.

## Atualização no navegador

[static/notifications.js](../static/notifications.js) consulta o contador a cada trinta segundos quando a página está visível, online e sem escrita/requisição concorrente. Também atualiza ao recuperar foco ou conexão.

Uma requisição possui timeout de oito segundos. Falhas de rede preservam o último valor válido e não interrompem edição. Respostas 401/403 interrompem a atualização daquela sessão.

`notification-state.js` mantém uma revisão compartilhada. Respostas antigas de polling não sobrescrevem um contador mais recente após leitura ou atualização das conexões. O sino recebe um nome acessível coerente com a quantidade e oculta a contagem zero no cabeçalho.

## Aprimoramento progressivo

Com JavaScript, ações de leitura atualizam o fragmento e feedback. Sem JavaScript, formulários enviam normalmente, preservando o caminho HTTP e os filtros de retorno pertinentes.

Horários são apresentados a partir de timestamps UTC e podem receber formatação relativa/local no navegador. A ordem do evento depende da identidade no banco, não da posição de um relógio do cliente.

## Privacidade e testes

As respostas da caixa e contador são privadas e usam `no-store`. Outro usuário não pode marcar, consultar ou abrir uma notificação por conhecer seu ID. Exclusão de conta remove notificações recebidas por cascata e eventos em que a conta era ator pelo serviço de exclusão.

Regressões em `test_notifications.py` e `test_browser_notifications.py` verificam propriedade, filtros, CSRF, leitura e concorrência de atualização. Alterações na caixa devem considerar o contador compartilhado nas conexões e no cabeçalho.
