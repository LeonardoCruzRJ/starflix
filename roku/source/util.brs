' 62.1: utilidades compartilhadas (incluídas pelos componentes que precisam).

' ---- guardado no registro do aparelho (sobrevive a reinício e atualização do canal) ----
function StoreGet(key as string, fallback = "" as string) as string
    sec = CreateObject("roRegistrySection", "starflix")
    if sec.Exists(key) then return sec.Read(key)
    return fallback
end function

sub StoreSet(key as string, value as string)
    sec = CreateObject("roRegistrySection", "starflix")
    sec.Write(key, value)
    sec.Flush()
end sub

sub StoreDelete(key as string)
    sec = CreateObject("roRegistrySection", "starflix")
    sec.Delete(key)
    sec.Flush()
end sub

' Endereço digitado -> "http://host:porta" (sem barra final). Sem esquema vira http; http sem porta usa 32000.
function NormalizeServer(raw as string) as string
    s = raw.Trim()
    if s = "" then return ""
    scheme = "http://"
    low = LCase(s)
    if Left(low, 8) = "https://"
        scheme = "https://"
        s = Mid(s, 9)
    else if Left(low, 7) = "http://"
        s = Mid(s, 8)
    end if
    slash = Instr(1, s, "/")
    if slash > 0 then s = Left(s, slash - 1)
    if s = "" then return ""
    if scheme = "http://" and Instr(1, s, ":") = 0 then s = s + ":32000"
    return scheme + s
end function

' Fonte do sistema (negrito ou normal) no tamanho pedido.
sub Style(node as object, size as integer, bold as boolean)
    di = CreateObject("roDeviceInfo")
    if Instr(1, di.GetFriendlyName(), "BrightScript Engine") > 0 ' 62.18: no emulador (brs) um nó Font esconde o Label; lá só o tamanho (sem negrito)
        node.font.size = size
        return
    end if
    f = CreateObject("roSGNode", "Font")
    if bold then f.uri = "font:BoldSystemFontFile" else f.uri = "font:SystemFontFile"
    f.size = size
    node.font = f
end sub

' URL de imagem do servidor para o `Poster` (que não manda cabeçalho): caminho da API + token curto `it` (GET /api/tv/img-token).
function ImgUrl(base as string, token as string, path as string) as string
    if path = "" then return ""
    if token = "" then return base + path
    sep = "?"
    if Instr(1, path, "?") > 0 then sep = "&"
    return base + path + sep + "it=" + token
end function

' Texto codificado para a URL (busca).
function UrlEnc(s as string) as string
    return CreateObject("roUrlTransfer").Escape(s)
end function

' Texto de uma chave do JSON ("" se não existir ou não for texto).
function JStr(obj as dynamic, key as string) as string
    if type(obj) = "roAssociativeArray"
        if obj.DoesExist(key)
            v = obj[key]
            if GetInterface(v, "ifString") <> invalid then return v
        end if
    end if
    return ""
end function

' Textos da tela: do catálogo do servidor no idioma do usuário (62.9); esta tabela pt-BR só vale sem conexão/antes de carregar.
function tr(key as string) as string
    t = {
        srv_title: "Conectar ao servidor"
        srv_hint: "Digite o endereço do servidor StarFlix, por exemplo 192.168.0.10:32000"
        srv_manual: "Digitar endereço"
        srv_search: "Procurar na rede"
        srv_searching: "Procurando servidores na rede…"
        srv_dlg_title: "Endereço do servidor"
        srv_dlg_msg: "IP ou domínio; a porta só é preciso se não for a 32000"
        btn_ok: "OK"
        btn_cancel: "Cancelar"
        srv_checking: "Procurando o servidor…"
        srv_fail: "Não encontrei um servidor StarFlix nesse endereço."
        pair_title: "Autorize esta TV"
        pair_step1: "No celular ou no computador, abra:"
        pair_step2: "e digite o código:"
        pair_waiting: "Aguardando autorização…"
        pair_offline: "Sem conexão com o servidor. Tentando de novo…"
        pair_hint: "Pressione * para trocar de servidor"
        pair_loading: "Pedindo o código…"
        prof_title: "Quem está assistindo?"
        prof_hint: "Pressione * para desconectar esta TV"
        prof_loading: "Carregando perfis…"
        prof_none: "Esta conta não tem perfis."
        prof_fail: "Não foi possível escolher o perfil. Tente de novo."
        done_title: "TV conectada"
        done_msg: "Conectada ao servidor"
        done_profile: "Perfil:"
        done_switch: "Trocar de perfil"
        done_logout: "Desconectar esta TV"
        home_loading: "Carregando o Início…"
        home_side_home: "Início"
        home_empty: "Nada para mostrar ainda."
        nav_loading: "Carregando…"
        nav_fail: "Não foi possível abrir. Tente de novo."
        grid_empty: "Nada por aqui ainda."
        play_fail: "Não foi possível reproduzir este vídeo."
        sub_off: "Legendas desligadas"
        sub_track: "Legenda"
        skip_intro: "Baixo: pular abertura"
        skip_credits: "Baixo: pular créditos"
        det_play: "Reproduzir"
        det_resume: "Continuar de"
        det_continue: "Continuar"
        det_season: "Temporada"
        det_special: "Especiais"
        det_related: "Semelhantes"
        det_prev: "Episódio anterior"
        det_next: "Próximo episódio"
        det_show: "Ver a série"
        det_dir: "Direção:"
        det_cast: "Elenco:"
        home_offline: "Sem conexão com o servidor. Tentando de novo…"
        home_side_search: "Busca"
        home_side_mylist: "Minha Lista"
        search_title: "Busca"
        search_dlg_title: "Buscar"
        search_dlg_msg: "Digite o título de um filme, série ou vídeo"
        det_watched: "Marcar como assistido"
        det_unwatched: "Marcar como não assistido"
        det_list_add: "Adicionar à Minha Lista"
        det_list_del: "Remover da Minha Lista"
        act_fail: "Não foi possível salvar. Tente de novo."
    }
    g = m.global ' 62.9: catálogo do servidor (chaves roku.*), carregado pelo MainScene; a tabela acima é a reserva
    if g <> invalid and g.hasField("strings")
        s = g.strings
        if type(s) = "roAssociativeArray" and s.DoesExist("roku." + key) then return s["roku." + key]
    end if
    if t.DoesExist(key) then return t[key]
    return key
end function

' Número inteiro de uma chave do JSON (fallback se não existir ou não for número).
function JInt(obj as dynamic, key as string, fallback = -1 as integer) as integer
    if type(obj) = "roAssociativeArray"
        if obj.DoesExist(key)
            v = obj[key]
            if GetInterface(v, "ifInt") <> invalid then return v
            if GetInterface(v, "ifFloat") <> invalid then return Int(v)
        end if
    end if
    return fallback
end function

' Episódio em andamento: "T1 E3 · título"; demais: o `sub` do servidor.
function CardSub(it as object) as string
    s = JStr(it, "sub")
    se = JInt(it, "season", -1)
    ep = JInt(it, "episode", -1)
    if JStr(it, "type") = "episode" and se >= 0 and ep >= 0
        pre = "T" + Str(se).Trim() + " E" + Str(ep).Trim()
        if s <> "" then return pre + " · " + s
        return pre
    end if
    return s
end function

' Junta os textos não vazios com o separador.
function JoinParts(parts as object, sep as string) as string
    out = ""
    for each p in parts
        if p <> ""
            if out <> "" then out = out + sep
            out = out + p
        end if
    end for
    return out
end function

' Segundos -> "1 h 52 min" / "47 min" (vazio sem duração).
function DurTxt(sec as integer) as string
    if sec <= 0 then return ""
    mins = Int(sec / 60)
    if mins < 1 then mins = 1
    h = Int(mins / 60)
    if h > 0 then return Str(h).Trim() + " h " + Str(mins - h * 60).Trim() + " min"
    return Str(mins).Trim() + " min"
end function

' Posição em segundos -> "23:10" ou "1:05:09".
function ClockTxt(sec as integer) as string
    h = Int(sec / 3600)
    m2 = Int((sec - h * 3600) / 60)
    s2 = sec - h * 3600 - m2 * 60
    ss = Str(s2).Trim()
    if s2 < 10 then ss = "0" + ss
    if h > 0
        mm = Str(m2).Trim()
        if m2 < 10 then mm = "0" + mm
        return Str(h).Trim() + ":" + mm + ":" + ss
    end if
    return Str(m2).Trim() + ":" + ss
end function

' Nota do JSON (número ou texto) como texto; "" se não existir ou for 0.
function NumTxt(obj as dynamic, key as string) as string
    if type(obj) <> "roAssociativeArray" then return ""
    if not obj.DoesExist(key) then return ""
    v = obj[key]
    if GetInterface(v, "ifString") <> invalid then return v
    if GetInterface(v, "ifInt") <> invalid
        if v = 0 then return ""
        return Str(v).Trim()
    end if
    if GetInterface(v, "ifFloat") <> invalid
        if v = 0 then return ""
        return Str(Int(v * 10) / 10).Trim()
    end if
    return ""
end function

' Número (inteiro ou decimal) de uma chave do JSON como Float; 0 se não existir.
function JNumF(obj as dynamic, key as string) as float
    if type(obj) = "roAssociativeArray"
        if obj.DoesExist(key)
            v = obj[key]
            if GetInterface(v, "ifFloat") <> invalid or GetInterface(v, "ifInt") <> invalid then return v
        end if
    end if
    return 0.0
end function
