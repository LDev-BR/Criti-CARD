# Criti-CARD

Criti-CARD é um projeto pessoal que desenvolvi durante meu período no
**Senac**, com o objetivo de colocar em prática tudo o que aprendi na
época sobre desenvolvimento web.

A aplicação funciona como uma **mini rede social**, onde os usuários
podem criar cards contendo críticas e avaliações sobre coisas de sua
preferência --- como jogos, filmes, séries, livros, etc.

### 📌 Exemplo de card:

> **Baldur's Gate 3**\
> Nota: 100\
> Descrição: O porquê acredito que essa nota esteja correta, destacando
> pontos fortes, experiência pessoal e impacto da obra.

------------------------------------------------------------------------

## 🚀 Tecnologias utilizadas

-   Python (Flask)
-   HTML
-   CSS
-   SQLite
-   Pillow (upload e validação de imagens)
-   dotenv

------------------------------------------------------------------------

## 🎯 Objetivo do projeto

O principal objetivo do Criti-CARD foi servir como um projeto prático de
aprendizado, reunindo em uma única aplicação conceitos como:

-   Autenticação de usuários
-   Criação e gerenciamento de contas
-   Upload de imagens
-   Sistema de permissões (admin)
-   Banco de dados relacional
-   Sessões
-   Validações de formulários
-   Interface web com templates HTML

------------------------------------------------------------------------

## 🧠 Sobre o sistema

No Criti-CARD:

-   Usuários podem se cadastrar e fazer login.
-   Cada usuário possui um perfil personalizado.
-   É possível criar cards com título, nota, imagem de capa e descrição.
-   Administradores possuem funções extras, como listar usuários e
    mensagens.
-   Existe um formulário de contato dentro da plataforma.

------------------------------------------------------------------------

## ▶️ Como executar o projeto

1.  Clone o repositório:

``` bash
git clone https://github.com/LDev-BR/Criti-CARD.git
```

2.  Entre na pasta:

``` bash
cd Criti-CARD
```

3.  Instale as dependências:

``` bash
pip install
```

4.  Crie um arquivo `.env` com:

    SECRET_KEY=sua_chave_secreta
    ADM_USERNAME=admin
    ADM_SENHA=senha_forte

5.  Execute:

``` bash
python app.py
```

------------------------------------------------------------------------

## 📄 Licença

Este projeto está sob a licença MIT.

------------------------------------------------------------------------

Desenvolvido como projeto pessoal para estudo e prática de
desenvolvimento web.
