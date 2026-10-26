# StarFlix — APK (celular e TV)

Um só APK (`com.starflix.app`). Celular: tela de conexão (rede, QR, link ou endereço) → WebView + player. TV (Android TV / Google TV): interface nativa em Compose for TV, controlada pelo D-pad.

## Gerar

Requer JDK 17 e Android SDK. Na raiz do projeto: `./scripts/build\\\_apk.sh` → `starflix.apk`. Guarde `android/starflix.jks` e `android/keystore.properties`.

## Instalar na TV

* **adb:** TV com "Depuração USB/rede" ligada → `adb connect IP-DA-TV:5555` → `adb install -r starflix.apk`.
* **Sideload:** copie o APK para um pendrive ou use um app de arquivos / "Send Files to TV" e abra no aparelho (permita fontes desconhecidas).
* O app aparece no menu da TV como StarFlix (`LEANBACK\\\_LAUNCHER`).

## Primeiro uso na TV

1. A TV procura o servidor na rede (mDNS); achou, segue sozinha (vários = lista). Não achou: **Conectar pelo celular** (QR para ler em Configurações → Conectar uma TV → Ler QR code da TV, no app do celular já conectado) ou **Digitar endereço** (`http://IP:32000`) com o teclado na tela.
2. Pelo celular, a TV vai direto aos perfis; pelo endereço, escaneie o QR (ou abra `/tv` e digite o código de 6 caracteres) com o usuário logado.
3. Escolha o perfil. Revogar: `/tv` (usuário) ou painel (admin); "Desconectar esta TV" no menu.

## Primeiro uso no celular

Tela de conexão: o app procura o servidor na rede (mDNS) e mostra **Servidor encontrado**; também lê o **QR code** de Configurações → Conectar Celular (a câmera só é pedida aí), aceita o **link** colado ou aberto (`starflix://connect`) e, por último, o endereço digitado. Sempre há um modal de confirmação antes de conectar. **Kotlin não compilado** — validar no aparelho.

## Controle remoto

* Player: fora dos controles, OK = pausa/play e ←/→ = ±10 s (segurando ±30 s); ↑ = ícones (←/→ trocam, OK abre, ↓ volta); ↓ = barra (a bolinha aparece, ←/→ movem, OK aplica, ↑ volta); Voltar sai do estado atual antes de fechar. Demais telas: OK = selecionar; Voltar = tela anterior (no Início e na escolha de perfil, fecha o app).

## Reproduzir a seguir (launcher da TV)

O Continue assistindo e o próximo episódio das séries assistidas aparecem na linha "Reproduzir a seguir" da tela inicial da TV (`WatchNextProgram`, `GET /api/tv/watchnext`); OK abre o app e continua a reprodução (`starflix://item?type=…\\\&id=…\\\&play=1`).

* **Atualiza** ao abrir o app, ao voltar do player (item assistido sai, próximo entra), ao escolher o perfil e ao ligar o interruptor.
* **Limpa** ao trocar de perfil (só os do perfil novo voltam), em "Desconectar esta TV", quando o token é revogado (401) ou o perfil é apagado (403), e ao desligar o interruptor.
* **Interruptor:** menu lateral → Mais → "Mostrar no início da TV" (ligado por padrão; só aparece em TV com Android 8+).
* Capas: o launcher não envia cabeçalho, então o app baixa as miniaturas para `cacheDir/watchnext/` e as serve pelo `StarflixImageProvider` (somente leitura).
* Se a linha não aparecer, a TV pode não liberar `WRITE\\\_EPG\\\_DATA` ou usar outro launcher; o app segue normal. **Kotlin não compilado** — validar na TV real.

