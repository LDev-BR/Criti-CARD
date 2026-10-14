# Jornada, XP e acesso por nível

A jornada reconhece participação por eventos persistidos, com origem e chave únicas por pessoa. A política em [progression/policy.py](../criticard/progression/policy.py) é independente de Flask; serviços aplicam a política dentro da transação da ação original.

## Fontes de XP

| Evento | Crédito base | Identidade |
| --- | --- | --- |
| Primeira crítica publicada de uma obra | 40 XP | `card:<work_id>` |
| Primeira conclusão de uma obra no backlog | 15 XP | `completed:<work_id>` |
| Atividade válida em uma semana ISO | 10 XP | `week:<ano>-<semana>` |
| Permanência de 30 dias | 50 XP | `tenure:30` |
| Permanência de 90 dias | 100 XP | `tenure:90` |
| Permanência de 180 dias | 150 XP | `tenure:180` |
| Primeiro aniversário de 365 dias | 250 XP | `anniversary:1` |
| Cada aniversário seguinte, por bloco de 365 dias | 500 XP | `anniversary:<ano>` |

As ações que registram atividade incluem publicação/edição efetivamente alterada de crítica, inclusão/alteração de backlog, novo comentário de card e nova publicação/comentário de comunidade. A origem semanal é única; repetir ações não multiplica os 10 XP da mesma semana.

Curtidas, follows, login e envio de mensagem de chat não constituem uma fonte própria de XP. Login sincroniza permanência e concessões já elegíveis. A simples presença da conta não inicia o tempo de primeira contribuição usado nos gates sociais.

Excluir e republicar a mesma obra, ou alternar entre concluído e outro estado, reutiliza a chave da fonte. A mesma pessoa não recebe novamente 40/15 XP por esse expediente.

## Cota e calendário

O limite é **200 XP por dia UTC** para eventos de origem `live`. Crédito pode ser parcial quando a margem disponível é menor que o valor base. Eventos que encontram a cota esgotada são registrados com zero e explicação.

Uma fonte registrada com zero não se torna crédito pendente para outro dia. A soma diária considera créditos positivos `live`; uma correção posterior não reabre automaticamente essa cota de concessão.

Origens `history` e `tenure` não consomem a cota diária de participação. Datas e semanas são calculadas em UTC; perto da meia-noite, o dia de cota pode diferir do dia local brasileiro.

O evento armazena versão de regra, origem, delta, dia, momento, obra/categoria quando pertinentes e eventual referência de reversão. O total acumulado fica no perfil de progressão, sob lock do titular.

## Curva de níveis

O nível é calculado a partir do saldo, sem número de ponto flutuante. Nível 1 começa em zero.

| Para alcançar | Custo de cada avanço |
| --- | --- |
| Níveis 2 a 5 | 125 XP |
| Nível 6 e níveis 7 a 20 | 100 XP |
| Níveis 21 a 40 | 125 XP |
| Níveis 41 a 60 | 150 XP |
| Níveis 61 a 80 | 200 XP |
| Níveis 81 a 100 | 250 XP |
| Níveis 101 a 120 | 300 XP |
| Cada bloco seguinte de vinte níveis | +50 XP no custo por avanço |

Assim, níveis 2, 3, 5 e 6 exigem respectivamente 125, 250, 500 e 600 XP acumulados. O nível continua além de 100; a apresentação de tier fica no último tier disponível.

## Tiers e recompensas

| Nível inicial | Tier | Material base |
| --- | --- | --- |
| 1 | Iniciante | Clássico |
| 11 | Aprendiz | Ardósia |
| 21 | Explorador | Bronze |
| 31 | Entusiasta | Cobre |
| 41 | Crítico | Prata |
| 51 | Analista | Safira |
| 61 | Curador | Ouro |
| 71 | Especialista | Platina |
| 81 | Mestre | Obsidiana |
| 91 | Lendário | Obsidiana e ouro |

Cada tier oferece título, moldura e acabamento de card. Conquistas incluem primeira crítica, críticas de 5/10 obras, três categorias, cinco conclusões, quatro semanas de participação sem sequência obrigatória, pioneiro, marcos de permanência e marcos de nível a cada cinco até 100.

Moldura Aurora depende de 90 dias e Patrimônio do primeiro aniversário. Selos podem destacar conquistas. O catálogo de tokens é permitido explicitamente; a personalização não aceita CSS ou paths fornecidos pelo usuário.

Concessões são reconciliadas com o extrato válido. Escolher uma recompensa exige possuí-la e ela estar vigente; cosméticos que perderem elegibilidade após correção voltam a escolhas permitidas.

## Privacidade e aviso

`/jornada` é uma área privada com extrato paginado e filtros de conquistas. `progression_public` vem `False`: a pessoa pode exibir nível, tier e adornos no perfil/cards, mas o extrato não se torna público.

Avisos de progresso vêm ativados e podem ser desativados. Avisos silenciados são consumidos para que a reativação não despeje uma fila antiga. Equipamentos padrão são Iniciante, moldura Clássico, card Clássico e nenhum selo.

`POST /jornada/sincronizar` não recebe pontos nem identificador de outra conta; ele calcula o progresso do titular. `POST /jornada/personalizar` salva escolhas permitidas.

## Gates dos espaços sociais

| Ação | Nível mínimo base | Tempo desde a primeira contribuição | Dias distintos de cota completa |
| --- | --- | --- | --- |
| Entrar em chat aberto | 3 (250 XP) | 24 horas | Nenhum |
| Entrar em chat fechado | 6 (600 XP) | 48 horas | 3 |
| Criar chat em grupo | 6 (600 XP) | 48 horas | 3 |
| Criar comunidade | 1 | 168 horas (7 dias) | Nenhum |
| Entrar em comunidade aberta/fechada | 1 | Sem espera base | Nenhum |

Chats e comunidades podem configurar um nível mínimo maior para entrada. O nível exigido é o maior entre gate base e configuração do espaço; criação de comunidade usa seu gate próprio. Convites e aprovação não dispensam a verificação final de acesso.

“Dia de cota completa” é um dia UTC cuja soma de créditos positivos `live`, excluindo eventos revertidos, é exatamente 200. São dias distintos, sem necessidade de sequência. XP histórico e permanência não completam esse requisito.

Primeira contribuição é um marco de atividade válida `live`, não a data de cadastro. Uma conta antiga com XP importado não ganha automaticamente o tempo e os dias de participação necessários a chats fechados.

O servidor devolve motivos como falta de contribuição, tempo restante, XP/nível ou dias de cota. A interface apresenta o motivo; conhecer a URL ou alterar um controle não concede entrada.

## Importação histórica explícita

```bash
python -m flask --app criticard progression-import-history --dry-run
python -m flask --app criticard progression-import-history --user-id 42 --dry-run
python -m flask --app criticard progression-import-history --user-id 42
```

O comando reconhece obras com críticas publicadas e backlog concluído, sem reconstruir semanas inventadas. Origens são `history`; contas inativas são ignoradas. Um marcador por conta torna a operação retomável e impede importação repetida.

`--dry-run` calcula e reverte alterações, incluindo concessões e marcador. O ID acima é um exemplo e deve ser substituído por uma conta do ambiente que você administra. Consulte backup e manutenção em [Operação](operations.md).

## Correção administrativa

`/admin/jornada/<user_id>` apresenta o histórico administrativo. `POST /admin/jornada/eventos/<event_id>/revogar` exige motivo de 10 a 500 caracteres e registra um evento inverso, em vez de apagar a origem.

Uma origem só pode ser revertida uma vez; correção não corrige outra correção. O serviço impede saldo negativo, recalcula primeira contribuição a partir de eventos válidos e reconcilia concessões. Os dias de cota dos gates passam a excluir a origem revertida.

## Verificar mudanças na política

Alterações exigem exemplos de fronteira: ganho parcial, zero, repetição, passagem UTC, semana ISO, permanência, nível 100+, concorrência, reversão e privacidade. As suítes `test_progression_*` separam política pura, HTTP, histórico, administração, SQLite e PostgreSQL.

Não altere o saldo diretamente para “liberar” uma tela em testes de regressão de gates; monte os eventos e os marcos que a regra efetivamente consulta. Dados de demonstração podem ser preparados em banco descartável, com origem documentada.
