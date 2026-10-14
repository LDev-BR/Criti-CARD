# Segurança

Este arquivo explica como comunicar possíveis vulnerabilidades e quais evidências ajudam a reprodução. A existência dos controles descritos não equivale a uma auditoria independente ou garantia de ausência de falhas.

## Comunicação privada

Se o repositório GitHub tiver **Private Vulnerability Reporting** habilitado, use a opção de reportar vulnerabilidade na aba **Security** do próprio repositório. A disponibilidade desse recurso precisa ser conferida no GitHub; este documento não presume que já esteja ativado.

Se a opção não estiver disponível, solicite ao mantenedor um canal privado antes de compartilhar detalhes sensíveis. Uma mensagem pública para pedir esse canal deve conter somente a intenção de relatar um problema, sem prova de exploração ou dados de terceiros.

Não existe um email de segurança público ou prazo de resposta definido neste repositório. Não use um endereço de exemplo de `.env` como contato real. O canal de privacidade da aplicação tem finalidade própria e não substitui automaticamente um canal de vulnerabilidades.

## Conteúdo do relato

Inclua, quando possível:

- Revisão/commit observado e configuração pertinente sem segredos.
- Área, rota ou evento Socket.IO afetado.
- Pré-condições e papel da conta: visitante, usuário, participante ou administrador.
- Passos reproduzíveis usando banco descartável e pessoas fictícias.
- Comportamento esperado e observado, com impacto concreto.
- Diferenças entre SQLite/PostgreSQL ou HTTP/socket, quando relevantes.
- Evidência mínima, como trecho de resposta com dados sensíveis removidos.

Não inclua bancos pessoais, exports, emails `.eml`, cookies, chaves ou hashes reais. Uma prova útil não depende de atingir outra instalação ou conta sem autorização.

## Áreas de atenção

| Fronteira | Controle implementado a preservar |
| --- | --- |
| Sessão | Identidade ligada a credenciais, estado ativo e versão de sessão |
| Mutação HTTP | Token CSRF e autorização no servidor |
| Conteúdo privado | Titular, membro ou papel necessário, incluindo contagens/previews |
| Chat | Origem/CSRF no ingresso e identidade/associação em eventos e entrega |
| Recuperação | Token aleatório com hash, validade, finalidade e consumo único |
| Upload | Formato real permitido, limite, regravação e nome único |
| Consulta | SQLAlchemy e binds, sem interpolação de entrada |
| Produção | Segredo explícito, PostgreSQL, HTTPS, host permitido e SMTP seguro |

Relatos sobre falhas nesses controles são especialmente úteis. Também considere concorrência: uma sessão revogada ou bloqueio realizado enquanto outra operação está em andamento pode revelar um caminho diferente do fluxo sequencial.

## Instalação e operação

Antes de disponibilizar uma instalação, siga [Configuração](docs/configuration.md) e [Operação](docs/operations.md). `app.py` e `run.ps1` oferecem execução local; a imagem de produção usa Gunicorn com um worker e threads, sob proxy adequado.

Segredos devem ficar fora do Git e do contexto Docker. `.gitignore` e `.dockerignore` excluem artefatos privados conhecidos, incluindo `criticard-dados-*.json`; arquivos já versionados exigem revisão do histórico e retirada específica.

Mantenha acesso restrito a banco, backups e spool de email, pois eles contêm dados privados. A aplicação não fornece sincronização distribuída de sockets ou política automática de retenção de todos esses artefatos.

## Mudanças e verificação

Para propor correção, proteja a propriedade afetada com uma regressão significativa e confira caminhos HTTP, JSON e socket pertinentes. Mudanças de autenticação, privacidade ou esquema exigem ampliar a verificação à suíte completa e, quando aplicável, a PostgreSQL/navegador.

Os comandos e a CI estão em [Testes](docs/testing.md). Não apresente execução ignorada ou validação de YAML como comprovação de segurança da aplicação em produção.

## Suporte de versões

O repositório não declara uma matriz de versões de produto com manutenção de segurança nem um SLA. Ao relatar, use a revisão atual quando possível e informe a revisão anterior em que identificou o problema.

A atualização de dependências e a revisão de uma instalação precisam ser verificadas pelo mantenedor. Uma dependência fixada ou proposta pelo Dependabot não deve ser atualizada sem avaliar compatibilidade e resultados dos testes relevantes.
