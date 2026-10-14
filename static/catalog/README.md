# Ilustrações do catálogo

Seis artes originais geradas em 7 de outubro de 2026 com a ferramenta integrada `image_gen.imagegen`, em modo de geração. Os prompts completos estão em `prompts.json`. Não houve download de capas oficiais, hotlinks, chamada à CLI/API nem edição posterior dos bitmaps.

Arquivos finais: `jogos-atlas.png`, `filmes-atlas.png`, `series-atlas.png`, `livros-atlas.png`, `animes-atlas.png` e `mangas-atlas.png`. Cada imagem tem 1881 × 836 pixels e uma grade sem espaçamento de 3 colunas por 2 linhas; cada painel tem proporção 3:2. Os cinco primeiros painéis ilustram, na ordem, as obras da categoria registrada em `criticard/catalog_images.py`; o sexto painel é decorativo. O recorte acontece em `static/catalog.css`, mantendo o arquivo gerado intacto.

Os prompts pediram cenas temáticas próprias, sem texto, logotipos, personagens identificáveis nem reprodução de layouts de capas ou cartazes. A interface identifica as imagens como ilustrações temáticas. Essas imagens não indicam associação com os autores ou titulares das obras.

O vínculo usa título e categoria, independente do ID do banco; as migrações com o catálogo original continuam intactas. Capas locais personalizadas têm prioridade. Marcadores `catalog:<categoria>:<índice>` só resolvem os 30 itens explicitamente permitidos, e arquivos de usuários continuam separados em seus próprios locais.
