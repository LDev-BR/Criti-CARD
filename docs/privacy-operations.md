# Privacidade e exclusão de conta

Este documento descreve controles técnicos e tarefas operacionais implementados. Ele não é uma declaração de conformidade legal nem substitui decisões do responsável sobre finalidade, base legal, retenção ou atendimento.

## Fronteiras de visibilidade

| Informação | Comportamento |
| --- | --- |
| Nome, username, biografia e avatar | Dados de apresentação do perfil público |
| Crítica publicada | Visível no feed, perfil e detalhe, conforme filtros e bloqueios |
| Card histórico arquivado | Restrito ao autor; não aparece no feed público |
| Backlog privado | Consultado pelo titular; excluído de coleção e contagens públicas |
| Conversa e histórico | Exigem associação à conversa e regras atuais de acesso |
| Comunidade fechada | Publicações e dados internos dependem de associação |
| Notificação | Consultada e marcada como lida somente pelo destinatário |
| Extrato de XP | Privado; estilos públicos são uma projeção limitada e opcional |
| Pedidos de privacidade | Titular e administração, em canal separado do suporte |
| Email, hash de senha e tokens | Não pertencem ao perfil público |

Visibilidade do backlog é por entrada. Alterar a preferência inicial não modifica entradas existentes. Publicar uma crítica não torna automaticamente pública a entrada correspondente da coleção.

## Preferências e bloqueios

`message_policy` permite `all`, `friends` ou `nobody` para novos envios diretos. A mudança não apaga histórico permitido. `friend_request_policy` aceita `all`, `following` ou `nobody`; solicitações já recebidas continuam disponíveis para resposta.

Bloqueios são considerados nas duas direções. Bloquear remove follows entre o par e a amizade/solicitação incompatível. Também impede interações e restringe descoberta, histórico ou entrega de mensagens conforme as regras de cada área. Desbloquear remove apenas o bloqueio feito pela pessoa, sem restaurar vínculos.

Esses controles não tornam conteúdo já público confidencial: um visitante sem a identidade do titular não carrega seu conjunto pessoal de bloqueios. Pessoas também podem ter copiado conteúdo que estava acessível. Não apresente bloqueio como revogação de todas as cópias existentes.

## Exportação pessoal

`GET /configuracoes/conta/exportar` exige sessão autenticada e retorna um anexo JSON da própria pessoa. O arquivo inclui perfil, preferências, críticas, coleção, follows, amizades, mensagens enviadas, registros próprios de grupos/comunidades, notificações, denúncias feitas, contatos, pedidos e progressão.

Não inclui hash de senha, tokens de recuperação ou o texto de mensagens enviadas por outros participantes. Identificadores e metadados de relações podem referenciar outras pessoas; o export é um recurso privado da conta.

O arquivo baixado passa a estar sob controle de quem o recebeu. Use dados fictícios ao revisar o formato e não acrescente exports pessoais a issues, capturas ou commits. O endpoint e os dados exportados estão em [accounts/settings.py](../criticard/accounts/settings.py).

## Pedidos de privacidade

`/privacidade` apresenta o aviso e os valores de `PRIVACY_CONTROLLER_NAME` e `PRIVACY_CONTACT_EMAIL`. O email vazio significa que não foi definido um canal externo nesse campo; a documentação não inventa um contato.

Para pessoas autenticadas:

1. `/privacidade/pedidos` recebe assunto e mensagem de 1 a 3000 caracteres.
2. O servidor atribui protocolo aleatório no formato `CC-<32 caracteres hexadecimais>`.
3. `/privacidade/pedidos/<protocol>` permite acompanhar status e respostas próprias.
4. A administração atende em `/admin/privacidade` e `/admin/privacidade/<protocol>`.

Os assuntos incluem acesso, correção, eliminação/anonimização/bloqueio, portabilidade, compartilhamento, consentimento, oposição/revisão e outros. Estados são `received`, `in_review` e `answered`.

Cada resposta administrativa acrescenta um registro ao histórico e atualiza o estado do pedido na mesma transação. O protocolo não substitui autorização: outra pessoa autenticada não ganha acesso por conhecê-lo.

As páginas/JSON dessa área usam `Cache-Control: no-store` e `Referrer-Policy: no-referrer`. Texto privado de formulário é mantido apenas na resposta de erro pertinente, sem ser copiado para flash/cookie. Não existe prazo automático de atendimento configurado.

## Senha, sessões e links

Troca de senha exige a senha atual, altera o hash, incrementa a versão e invalida links anteriores; a sessão que realizou a troca só é atualizada após nova conferência das credenciais. Encerrar sessões incrementa a versão e encerra também a sessão atual.

Recuperação usa resposta genérica e tokens aleatórios cujo hash fica no banco. Os defaults de expiração são 30 minutos para recuperação e 24 horas para verificação. Consumo é único e também depende de email e versão de sessão compatíveis.

Sockets revalidam identidade durante eventos e entrega. Revogar sessão não deve ser interpretado como retirar o que já foi mostrado no navegador; a proteção se aplica a operações e entregas subsequentes.

## Exclusão pelo titular

`/excluir_user` e `/delete` apresentam o fluxo. A mutação exige CSRF e senha atual, com budget de tentativas. Antes da escrita, a linha da conta é bloqueada e sua identidade é novamente conferida.

O serviço de exclusão:

- Remove os cards e o texto de mensagens enviadas por essa conta.
- Remove posts e comentários autorais de comunidades e denúncias desses alvos.
- Remove relações pessoais e dados dependentes pela operação explícita e foreign keys.
- Remove denúncias feitas pela pessoa e notificações em que ela era o ator.
- Transfere propriedade de grupos/comunidades a um membro ativo elegível, quando houver.
- Arquiva espaços sem sucessor e retira metadados pessoais de criação conforme o modelo.
- Agenda avatares e capas sem referências para limpeza posterior.

Mensagens de outros participantes permanecem; excluir um participante não apaga a conversa dos demais. Conteúdo de outras pessoas subordinado a um post/card removido pode desaparecer por dependência desse alvo.

Em comunidades, sucessão prioriza moderador e depois ordem de associação/ID. Grupos usam moderador disponível, depois membro mais antigo. Os detalhes são implementados em `db.delete_user` e `chat.service.handle_user_deletion`.

## Exclusão administrativa e moderação

A exclusão administrativa de usuário reutiliza o serviço de exclusão. Não implemente remoção direta de `usuarios` em scripts avulsos, pois os preparativos de mensagens, propriedade e arquivos fazem parte da operação.

Remoção de mensagem de grupo pela moderação marca `redacted_at`/`redacted_by` para ocultar sua apresentação. Ela não é o mesmo procedimento de eliminação física do texto que ocorre na exclusão da conta. Retenção desses registros precisa ser considerada pelo operador.

Pedidos e respostas associados à conta são dependentes com cascata; o produto não mantém automaticamente um dossiê de atendimento após a exclusão. Se outra retenção for necessária, ela exige uma decisão específica de produto/operação.

## Remoção de imagens

Alterações de banco são confirmadas antes da limpeza do armazenamento. `pending_image_deletions` guarda somente tipo, nome de arquivo e momento de inclusão, sem manter a conta excluída ou seu texto privado.

Uma imagem ainda usada por usuário, crítica, obra ou comunidade é preservada. A verificação considera nomes antigos e diretórios compartilhados. No S3, a limpeza também remove eventual cópia local do mesmo nome.

```bash
python -m flask --app criticard privacy-cleanup-images --limit 100
```

Falhas deixam a fila para nova tentativa e o comando informa o resultado. A exclusão de conta não é desfeita por uma falha no armazenamento. A disponibilidade de URLs em caches externos ainda depende de cache/CDN e de sua política.

## Responsabilidades do ambiente

Backups, outbox, logs do proxy/provedor e arquivos já baixados não são eliminados retroativamente por `delete_user`. A caixa de email mantém mensagens em `sent/` e `discarded/`; defina acesso, retenção e limpeza para essas pastas.

Após restaurar um backup, reavalie exclusões e decisões posteriores ao ponto restaurado antes de reabrir a instalação. A restauração não deve reintroduzir silenciosamente conteúdo cuja remoção já foi atendida.

Antes de publicação, o responsável deve definir canal externo, fornecedores usados, acessos administrativos, retenção e procedimento de atendimento. O aviso configurável e os controles existentes são insumos técnicos para esse trabalho.

## Verificações relevantes

Use os testes de privacidade, exclusão administrativa, aposentadoria de avatar, exportação e PostgreSQL listados em [Testes](testing.md). Uma revisão deve exercitar titular, outra conta, administrador, sessão revogada e falha de armazenamento com dados descartáveis.
