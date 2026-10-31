# StarFlix para Roku (Fase 62)

> **Beta — não testado em aparelho.** O canal foi escrito e conferido só por leitura do código e pelo `build_roku.sh`; pode ter falhas na descoberta, no pareamento, nas imagens e na reprodução. Relate o que não funcionar.

Canal em BrightScript + SceneGraph. Não passa pela loja: é instalado pelo **modo desenvolvedor** da Roku.

1. Ative o modo desenvolvedor na Roku (controle: Home ×3, Cima ×2, Direita, Esquerda, Direita, Esquerda, Direita), defina uma senha e anote o IP.
2. Na raiz do projeto: `./scripts/build_roku.sh` (gera `starflix-roku.zip`).
3. No navegador, abra `http://IP-DA-ROKU`, entre com `rokudev` e a senha, envie o zip em **Upload** e clique em **Install**.
4. No canal: o servidor é achado na rede (ou digite o endereço), leia o código na tela e digite-o em `http://SERVIDOR:32000/tv`; escolha o perfil e o Início abre com menu lateral e fileiras; bibliotecas, coleções e detalhes abrem com OK e Voltar desempilha; Reproduzir abre o player (OK pausa, * legendas, Baixo pula abertura). Tecla `*` troca de servidor (pareamento) ou desconecta (perfis).

Depuração: `telnet IP-DA-ROKU 8085`.

## Instalação direta e pacote .pkg (62.10)

- `./scripts/build_roku.sh --install IP SENHA` empacota e instala sem abrir o navegador (precisa do `curl`).
- **Pacote .pkg** (versão assinada para guardar): 1) gere a chave de assinatura na Roku com o `genkey`, como descreve a documentação oficial da Roku ("Packaging Roku apps"), e anote a **senha** e o **ID** da chave; 2) rode `./scripts/build_roku.sh --pkg IP SENHA SENHA_DA_CHAVE`; sai `starflix-roku.pkg`. Guarde a chave: sem ela não dá para atualizar o canal já assinado. O `--pkg` segue o procedimento do instalador web da Roku e **não foi testado**.
- O script confere antes de empacotar: arquivos citados nos XML e no `manifest` existem, `build_version` = `config.VERSION` e cada `sub`/`function` fecha.
- Não testado em aparelho: o que falta conferir está na 62.11 do `create.md`.
