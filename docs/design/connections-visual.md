# Interface de conexões

Este guia registra a composição e o comportamento atuais de `/conexoes`, como referência de manutenção. Ele descreve uma implementação existente, sem impor uma nova direção visual.

## Objetivo da tela

A tela reúne amizades e relações de acompanhamento em um lugar. A pessoa deve identificar em qual lista está, encontrar alguém, compreender a relação existente e realizar uma ação compatível sem perder contexto.

As seis abas são `amigos`, `recebidas`, `enviadas`, `seguindo`, `seguidores` e `descobrir`. Amizade depende de convite; seguir permanece independente. Essa distinção aparece na navegação e na mensagem de apoio.

## Composição

Em telas largas, uma navegação lateral acompanha a área de resultados. O painel de conteúdo apresenta título da aba, descrição curta, busca por nome/@usuário, lista de pessoas e paginação.

Cada linha contém avatar ou inicial, nome público, username, biografia curta e ações. Nome/username permitem quebra para evitar transbordamento. Biografia é uma informação auxiliar; não deve competir visualmente com identidade e ação.

Tokens compartilhados definem fundos escuros, bordas discretas, texto e destaque dourado. Manrope atende ao corpo/controles; Cormorant Garamond é usada em títulos e identidade visual. As fontes são locais com licenças presentes em `static/fonts/`.

## Estados e ações

| Lista/estado | Ações principais |
| --- | --- |
| Descoberta sem relação | Abrir perfil, seguir ou solicitar amizade quando permitido |
| Pedido recebido | Aceitar ou recusar |
| Pedido enviado | Cancelar |
| Amizade aceita | Conversar, abrir perfil e opções de desfazer |
| Seguindo | Alterar acompanhamento e abrir perfil |
| Sem resultado de busca | Explicação e limpar busca |
| Lista vazia | Mensagem própria da aba e descoberta quando pertinente |

O servidor fornece estado e contagens. A interface deve representar uma ação pendente e uma falha sem fingir que a relação foi alterada. Um resultado de escrita válido seguido de falha de atualização informa que a ação foi registrada e orienta atualizar a página.

## Busca e contexto

O formulário GET preserva `aba`, usa `q` e funciona sem JavaScript. Paginação conserva aba/busca. Buscar na aba de amigos não transforma silenciosamente a consulta em uma descoberta global.

O aprimoramento de busca troca apenas o fragmento pertinente e mantém URL navegável. Após uma ação, a tela atualiza conteúdo e contagens a partir do servidor; se a página atual deixa de existir porque a lista encolheu, ajusta para uma página válida.

Perfis usam os mesmos controles de relacionamento em seu contexto. O retorno dos formulários distingue perfil e lista; não utilize redirecionamentos livres enviados pelo navegador.

## Responsividade

Em larguras menores, colunas da linha são reorganizadas e a biografia/ações passam a ocupar novas linhas. A navegação lateral deixa de ser sticky e torna-se uma seleção compacta.

O template oferece `details`/`summary` para o seletor de listas. Esse elemento continua operável sem JavaScript. Em telas pequenas, alvos de ações possuem altura mínima de 44 pixels e o conjunto deve caber sem rolagem horizontal.

Não esconda ações necessárias apenas para encaixar a linha. Preserve nomes legíveis, feedback e acesso à seleção de listas com teclado e toque.

## Semântica e acessibilidade

- `nav` recebe nome acessível e a aba ativa usa `aria-current="page"`.
- A busca usa `role="search"`, label e botão com nome próprio.
- Resultados são uma lista; região de conteúdo referencia seu título.
- Mensagens de atualização usam `role="status"`.
- Ações em andamento recebem `aria-busy` e botão temporariamente desabilitado.
- Após atualizar fragmento, o foco volta à identidade ou ao título quando necessário.
- Escape fecha menus de opções e devolve foco ao `summary`.

Ícones acompanham palavras ou nomes acessíveis; cor e contadores não devem ser a única pista do estado. Preferências gerais de texto maior, contraste e redução de movimento precisam continuar aplicáveis.

## Arquivos envolvidos

| Arquivo | Papel |
| --- | --- |
| [people_views.py](../../criticard/social/people_views.py) | Abas, dados HTTP e retornos |
| [connections.py](../../criticard/social/connections.py) | Busca, contagens e relação de amizade |
| [connections.html](../../templates/social/connections.html) | Estrutura principal |
| [person_row.html](../../templates/social/person_row.html) | Linha de identidade e ações |
| [connections.css](../../static/connections.css) | Layout, estados e breakpoints |
| [connections.js](../../static/connections.js) | Escritas, atualização e foco |
| [live-search.js](../../static/live-search.js) | Busca progressiva e troca de fragmentos |

## Conferência após mudanças

Revise desktop e tela estreita, nome longo, biografia vazia, avatar ausente, busca sem resultados, solicitação recebida/enviada e lista que muda de página após ação. Exercite teclado, foco, Escape, menu nativo e formulário sem JavaScript.

As provas `test_connections_http.py`, `test_browser_connections.py`, `test_browser_accessibility.py` e `test_browser_responsive_shell.py` ajudam a verificar comportamento. Capturas de portfólio são registros ilustrativos de um ambiente fictício, não a única fonte de validação.
