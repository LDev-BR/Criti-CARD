# Catálogo administrativo

O catálogo é a fonte compartilhada de identidade e capa das obras. A administração controla obras; as pessoas mantêm críticas e entradas individuais de backlog vinculadas a elas.

## Rotas e permissão

| Rota | Método | Ação |
| --- | --- | --- |
| `/admin/obras` | GET | Lista com busca, categoria e estado |
| `/admin/obras/nova` | GET/POST | Formulário e criação |
| `/admin/obras/<id>/editar` | GET/POST | Edição de título, categoria e capa |
| `/admin/obras/<id>/excluir` | GET/POST | Confirmação e retirada do catálogo |
| `/admin/obras/<id>/reativar` | POST | Retorno ao catálogo ativo |

Todas exigem administrador. As mutações preservam CSRF, consomem o budget de segurança e revalidam a sessão após bloquear a identidade administrativa. Um botão escondido na interface não é o controle de autorização.

As regras ficam em [admin_catalog/service.py](../criticard/admin_catalog/service.py); [views.py](../criticard/admin_catalog/views.py) trata HTTP, upload, feedback e limpeza.

## Busca e listagem

Filtros usam `q`, `categoria` e `status`, com estados `active`, `archived` ou `all`. O default mostra obras ativas. Busca é textual literal e limitada; `%` não deve ser tratado como autorização para uma consulta curinga arbitrária.

A listagem mostra categoria, capa e contagens de referências em críticas/backlog. Paginação administrativa usa vinte itens por página por padrão. Essas contagens auxiliam a retirada, mas a operação não apaga usuários ou suas opiniões.

## Criar uma obra

1. Escolha categoria existente.
2. Informe título de 1 a 120 caracteres.
3. Envie uma capa PNG, JPG/JPEG ou GIF válida.
4. Confirme o formulário com a sessão administrativa atual.

A criação exige uma imagem. O servidor valida formato real, arquivo de até 3 MiB e dimensão de até 16 milhões de pixels. Regrava a imagem, aplica orientação EXIF e atribui nome único; extensão e tipo informado pelo navegador não bastam.

O catálogo inicial de migrações possui seis categorias e obras pré-cadastradas. O fluxo administrativo cria obras em categorias existentes; não há CRUD de categorias nessa tela.

## Unicidade de título

Título é normalizado com `strip()` e comparado por `casefold()` dentro da categoria. Uma obra retirada continua reservando o nome; a orientação é reativar o cadastro existente.

Em PostgreSQL, escritas administrativas bloqueiam categorias em ordem antes de bloquear a obra. Isso serializa a conferência de duplicatas sem reescrever títulos históricos. Em SQLite, a escrita de bloqueio da conta já reserva o writer.

Não simule unicidade apenas no frontend. Mudanças nesta regra devem ser verificadas também com escrita concorrente em PostgreSQL.

## Capas e identidade compartilhada

Novas críticas não enviam uma capa própria: escolhem uma obra e recebem sua imagem definida no catálogo. Cards publicados vinculados exibem a identidade atual da obra, inclusive após edição administrativa.

Para obras iniciais sem capa personalizada, [catalog_images.py](../criticard/catalog_images.py) resolve ilustrações locais por categoria/título e marcadores permitidos. O recorte usa os atlas de `static/catalog/`, sem hotlinks a capas oficiais.

Ao editar título/categoria sem nova imagem, o serviço conserva a arte anterior resolvida para evitar perder a representação da obra. Quando existe nova capa, a anterior é agendada para remoção somente se não houver outras referências.

Marcadores do catálogo e paths estáticos permitidos são tratados de forma específica; nomes arbitrários de arquivo não devem virar URL pública. Origem das artes está documentada em [static/catalog/README.md](../static/catalog/README.md).

## Retirada e reativação

A rota chamada `/excluir` **retira** a obra: define `active=0`. Ela não elimina a linha nem apaga as críticas/coleções existentes. O formulário mostra usos e exige confirmação explícita.

Obras retiradas deixam de ser novas opções no catálogo e nos fluxos que exigem obra ativa. Um card existente vinculado à obra pode continuar sendo editado com sua referência histórica permitida; tendências e feed de seguidos excluem obras inativas.

Reativar confere novamente o cadastro e torna `active=1`. Não crie um item paralelo só para recuperar uma obra retirada, pois isso quebra a identidade compartilhada das relações existentes.

## Falhas e imagens órfãs

Se validação ou sessão falhar após um upload, o novo arquivo é encaminhado à limpeza. Se a atualização confirmar mas a remoção da capa anterior falhar, o usuário recebe aviso de pendência e a fila permanece para repetição.

```bash
python -m flask --app criticard privacy-cleanup-images --limit 100
```

Não remova diretamente um arquivo compartilhado por card, obra ou comunidade. A verificação de referências do serviço protege esses usos.

## Revisão de mudanças

Ao alterar a administração, confira permissões, sessão revogada, duplicidade Unicode, capa inválida, obra retirada, preservação de referências e falha de armazenamento. Testes úteis incluem `test_admin_catalog.py`, `test_admin_catalog_postgres.py`, `test_catalog_card_images.py` e `test_browser_admin_catalog.py`.

Bootstrap do primeiro administrador está em [Primeiros passos](getting-started.md). Operações de banco e backup estão em [Operação](operations.md).
