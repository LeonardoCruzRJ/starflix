' 62.6: navegação (pilha de telas GridView/DetailView por cima do Início; Voltar desempilha).
' 62.5: Início (menu lateral + fileiras de /api/tv/home) em components/HomeView; estado "home".
' 62.1: conectar ao servidor (endereço digitado) e parear a TV por código (POST /api/tv/code + consulta a /api/tv/code/<poll>).
' 62.4: capas por URL com token curto de imagem (GET /api/tv/img-token -> `it`), renovado a cada 3 h; perfis em grade com foto.
' 62.3: escolha de perfil (GET /api/tv/profiles, POST /api/tv/profile/<id>); o perfil escolhido vai em `X-Profile` nas chamadas seguintes (AuthHeaders).
' Estados: "discover", "server" (lista/endereço), "checking", "pair" (mostra o código), "profiles", "retry", "home" (Início), "homeretry" (Início sem conexão).
sub init()
    m.tasks = {}
    m.state = ""
    m.polling = false
    m.poll = ""
    m.pending = ""
    m.found = []
    m.actions = []
    m.profiles = []
    m.forceList = false
    m.wanted = {}
    m.imgToken = ""
    m.after = ""
    m.libs = []
    m.stack = []
    m.colCount = 0
    m.cols = []
    m.nav = {}
    m.global.addFields({ strings: {}, lang: "" })
    m.strNext = ""
    m.homeStale = false
    m.detStale = false
    m.actBusy = false
    m.lastQuery = ""
    m.detView = invalid
    for each id in ["logo", "title", "line1", "url", "line2", "code", "status", "menu", "profGrid", "home", "notice", "noticeTimer", "hint", "pollTimer", "retryTimer", "imgTimer", "syncTimer"]
        m[id] = m.top.findNode(id)
    end for
    Style(m.logo, 84, true)
    Style(m.title, 52, true)
    Style(m.line1, 34, false)
    Style(m.url, 48, true)
    Style(m.line2, 34, false)
    Style(m.code, 128, true)
    Style(m.status, 32, false)
    Style(m.hint, 28, false)
    m.logo.text = "StarFlix"
    m.menu.observeField("itemSelected", "onMenu")
    m.pollTimer.observeField("fire", "onPollTick")
    m.retryTimer.observeField("fire", "onRetry")
    m.profGrid.observeField("itemSelected", "onProfileGrid")
    m.imgTimer.observeField("fire", "onImgTimer")
    m.home.observeField("action", "onHomeAction")
    m.home.observeField("picked", "onPicked")
    m.noticeTimer.observeField("fire", "onNoticeEnd")
    m.syncTimer.observeField("fire", "onSync")
    m.imgTimer.control = "start"
    m.top.setFocus(true)

    m.server = StoreGet("server")
    m.token = StoreGet("token")
    m.profile = StoreGet("profile")
    m.profileName = StoreGet("profile_name")
    if m.server = ""
        StartDiscovery()
    else if m.token = ""
        StartPairing()
    else
        CheckToken(false)
    end if
end sub

' Cabeçalhos das chamadas autenticadas: token do aparelho e, se já escolhido, o perfil.
function AuthHeaders() as object
    h = { Authorization: "Bearer " + m.token }
    if m.profile <> "" then h["X-Profile"] = m.profile
    return h
end function

sub Forget()
    StoreDelete("token")
    StoreDelete("device_id")
    StoreDelete("profile")
    StoreDelete("profile_name")
    m.token = ""
    m.profile = ""
    m.profileName = ""
    m.imgToken = ""
end sub

sub Request(url as string, method as string, body as string, headers as object, callback as string)
    t = CreateObject("roSGNode", "HttpTask")
    t.url = url
    t.method = method
    t.body = body
    t.headers = headers
    t.observeField("status", callback)
    m.tasks[callback] = t ' guarda a referência até a próxima chamada do mesmo tipo
    t.control = "RUN"
end sub

sub Clear()
    m.pollTimer.control = "stop"
    m.retryTimer.control = "stop"
    m.polling = false
    for each id in ["title", "line1", "url", "line2", "code", "status", "hint"]
        m[id].text = ""
    end for
    m.menu.visible = false
    m.profGrid.visible = false
    ClearStack()
    m.notice.text = ""
    m.home.visible = false
    m.logo.visible = true
    m.status.translation = [210, 830]
end sub

' ---- estados ----
sub ShowServer(err as string)
    Clear()
    m.state = "server"
    m.title.text = tr("srv_title")
    m.line1.text = tr("srv_hint")
    labels = []
    actions = []
    for each sv in m.found ' servidores achados na rede, depois as opções fixas
        label = sv.host + ":" + Str(sv.port).Trim()
        if sv.name <> "" then label = sv.name + "  (" + label + ")"
        labels.Push(label)
        actions.Push({ kind: "server", addr: "http://" + sv.host + ":" + Str(sv.port).Trim() })
    end for
    labels.Push(tr("srv_search"))
    actions.Push({ kind: "search" })
    labels.Push(tr("srv_manual"))
    actions.Push({ kind: "manual" })
    ShowMenu(labels, actions, err)
end sub

' Lista de opções (LabelList) com a mensagem de erro opcional logo acima.
sub ShowMenu(labels as object, actions as object, err as string)
    m.actions = actions
    m.status.translation = [210, 630]
    m.status.color = "0xFF6B6BFF"
    m.status.text = err
    content = CreateObject("roSGNode", "ContentNode")
    for each label in labels
        item = content.CreateChild("ContentNode")
        item.title = label
    end for
    m.menu.content = content
    rows = labels.Count()
    if rows > 4 then rows = 4
    m.menu.numRows = rows
    m.menu.translation = [660, 710]
    m.menu.visible = true
    m.menu.setFocus(true)
end sub

sub StartDiscovery()
    Clear()
    m.state = "discover"
    m.title.text = tr("srv_searching")
    m.top.setFocus(true)
    t = CreateObject("roSGNode", "DiscoverTask")
    t.observeField("done", "onDiscover")
    m.tasks["onDiscover"] = t
    t.control = "RUN"
end sub

sub ConnectTo(addr as string)
    m.pending = addr
    ShowChecking()
    Request(addr + "/api/server-info", "GET", "", {}, "onServerInfo")
end sub

sub onDiscover(event as object)
    if m.state <> "discover" then return
    m.found = event.getRoSGNode().found
    if m.found.Count() = 1 ' um só: conecta direto (o pareamento ainda pede a autorização no site)
        sv = m.found[0]
        ConnectTo("http://" + sv.host + ":" + Str(sv.port).Trim())
    else
        ShowServer("")
    end if
end sub

sub onMenu()
    idx = m.menu.itemSelected
    if idx < 0 or idx >= m.actions.Count() then return
    a = m.actions[idx]
    if a.kind = "server"
        ConnectTo(a.addr)
    else if a.kind = "search"
        StartDiscovery()
    else if a.kind = "manual"
        OpenKeyboard()
    else if a.kind = "switch"
        CheckToken(true)
    else if a.kind = "logout"
        DoLogout()
    end if
end sub

sub ShowChecking()
    Clear()
    m.state = "checking"
    m.title.text = tr("srv_checking")
    m.top.setFocus(true)
end sub

sub StartPairing()
    Clear()
    m.state = "pair"
    m.title.text = tr("pair_title")
    m.status.color = "0xB8B8C2FF"
    m.status.text = tr("pair_loading")
    m.hint.text = tr("pair_hint")
    m.top.setFocus(true)
    di = CreateObject("roDeviceInfo")
    name = "Roku " + di.GetModelDisplayName()
    Request(m.server + "/api/tv/code", "POST", FormatJson({ name: name }), {}, "onCode")
end sub

' Início: lê as bibliotecas e depois as fileiras; 401/403 volta ao pareamento, sem conexão tenta de novo a cada 15 s.
sub LoadHome()
    Clear()
    m.state = "homeload"
    m.title.text = tr("home_loading")
    m.top.setFocus(true)
    LoadStrings("home")
end sub

' 62.9: idioma do usuário (GET /api/tv/lang) e só as chaves roku.* do catálogo; falha = segue com os textos que já há.
sub LoadStrings(nextStep as string)
    m.strNext = nextStep
    Request(m.server + "/api/tv/lang", "GET", "", AuthHeaders(), "onLang")
end sub

sub onLang(event as object)
    t = event.getRoSGNode()
    lang = JStr(t.json, "lang")
    if t.ok and lang <> "" and lang <> m.global.lang
        Request(m.server + "/api/i18n/" + lang + "?prefix=roku.", "GET", "", {}, "onStrings")
    else
        StringsDone()
    end if
end sub

sub onStrings(event as object)
    t = event.getRoSGNode()
    if t.ok and type(t.json.strings) = "roAssociativeArray"
        m.global.strings = t.json.strings
        m.global.lang = JStr(t.json, "lang")
    end if
    StringsDone()
end sub

sub StringsDone()
    if m.strNext = "token"
        Request(m.server + "/api/tv/profiles", "GET", "", { Authorization: "Bearer " + m.token }, "onTokenCheck")
    else if m.strNext = "home"
        Request(m.server + "/api/tv/libraries", "GET", "", AuthHeaders(), "onLibs")
    end if
    m.strNext = ""
end sub

sub onLibs(event as object)
    if m.state <> "homeload" then return
    t = event.getRoSGNode()
    if t.status = 401 or t.status = 403
        Forget()
        StartPairing()
        return
    end if
    if not t.ok
        HomeOffline()
        return
    end if
    m.libs = []
    if type(t.json.libraries) = "roArray" then m.libs = t.json.libraries
    Request(m.server + "/api/tv/home", "GET", "", AuthHeaders(), "onHome")
end sub

sub onHome(event as object)
    if m.state <> "homeload" then return
    t = event.getRoSGNode()
    if t.status = 401 or t.status = 403
        Forget()
        StartPairing()
        return
    end if
    if not t.ok
        HomeOffline()
        return
    end if
    rows = []
    if type(t.json.rows) = "roArray" then rows = t.json.rows
    ShowHome(rows)
end sub

sub HomeOffline()
    Clear()
    m.state = "homeretry"
    m.title.text = tr("home_offline")
    m.retryTimer.control = "start"
end sub

sub ShowHome(rows as object)
    Clear()
    m.state = "home"
    m.logo.visible = false
    m.home.server = m.server
    m.home.imgToken = m.imgToken
    m.home.profileName = m.profileName
    m.home.libs = m.libs
    m.home.visible = true ' visível antes de montar: só nó visível recebe foco
    m.home.rows = rows ' por último: dispara a montagem
end sub

sub onHomeAction(event as object)
    act = event.getData()
    if act = "switch"
        CheckToken(true)
    else if act = "logout"
        DoLogout()
    else if Left(act, 8) = "library:"
        Navigate("library", Int(Val(Mid(act, 9))), 0)
    else if act = "mylist"
        Navigate("mylist", 0, 0)
    else if act = "search"
        OpenSearch()
    end if
end sub

' ---- 62.8: busca ----
sub OpenSearch()
    dlg = CreateObject("roSGNode", "KeyboardDialog")
    dlg.title = tr("search_dlg_title")
    dlg.message = tr("search_dlg_msg")
    dlg.text = m.lastQuery
    dlg.buttons = [tr("btn_ok"), tr("btn_cancel")]
    dlg.observeField("buttonSelected", "onSearchDlg")
    m.top.dialog = dlg
end sub

sub onSearchDlg(event as object)
    dlg = event.getRoSGNode()
    idx = dlg.buttonSelected
    q = dlg.text.Trim()
    dlg.close = true
    if idx <> 0 or q = "" then return
    m.lastQuery = q
    Notice(tr("nav_loading"), 0)
    Request(m.server + "/api/tv/search?q=" + UrlEnc(q), "GET", "", AuthHeaders(), "onSearch")
end sub

sub onSearch(event as object)
    t = event.getRoSGNode()
    if not t.ok
        NavFail(t)
        return
    end if
    its = []
    for each key in ["collections", "movies", "shows", "videos"]
        l = t.json[key]
        if type(l) = "roArray"
            for each it in l
                its.Push(it)
            end for
        end if
    end for
    PushGrid(tr("search_title") + ": " + JStr(t.json, "q"), its, its.Count())
end sub

' ---- 62.8: assistido, Minha Lista e atualização do que o player/ações mudaram ----
sub DoAction(p as object)
    if m.actBusy then return
    m.actBusy = true
    m.act = p
    h = AuthHeaders()
    if JStr(p, "act") = "watched"
        Request(m.server + "/api/tv/watched/" + JStr(p, "kind") + "/" + Str(JInt(p, "id", 0)).Trim(), "POST", FormatJson({ watched: p.value }), h, "onActDone")
    else
        method = "DELETE"
        if p.value = true then method = "POST"
        Request(m.server + "/api/tv/mylist/" + Str(JInt(p, "id", 0)).Trim(), method, "", h, "onActDone")
    end if
end sub

sub onActDone(event as object)
    m.actBusy = false
    t = event.getRoSGNode()
    if t.status = 401 or t.status = 403
        Forget()
        StartPairing()
        return
    end if
    if not t.ok
        Notice(tr("act_fail"), 4)
        return
    end if
    cur = Current()
    if m.stack.Count() > 0 and cur.subtype() = "DetailView"
        if JStr(m.act, "act") = "watched" then cur.patch = { watched: m.act.value } else cur.patch = { in_list: m.act.value }
    end if
    m.homeStale = true ' Continuar assistindo / Minha Lista mudam no Início
end sub

sub onSync()
    if m.stack.Count() = 0
        m.detStale = false
        if m.homeStale then RefreshHome()
        return
    end if
    cur = Current()
    if m.detStale and cur.subtype() = "DetailView"
        ref = cur.ref
        if type(ref) = "roAssociativeArray"
            m.detStale = false
            m.detView = cur
            Request(m.server + "/api/tv/" + JStr(ref, "kind") + "/" + Str(JInt(ref, "id", 0)).Trim(), "GET", "", AuthHeaders(), "onDetRefresh")
        end if
    end if
end sub

sub onDetRefresh(event as object)
    t = event.getRoSGNode()
    if t.ok and m.detView <> invalid then m.detView.data = t.json
end sub

sub RefreshHome()
    m.homeStale = false
    Request(m.server + "/api/tv/home", "GET", "", AuthHeaders(), "onHomeRefresh")
end sub

sub onHomeRefresh(event as object)
    if m.state <> "home" then return
    if m.stack.Count() > 0
        m.homeStale = true ' abriu outra tela no meio: refaz quando voltar ao Início
        return
    end if
    t = event.getRoSGNode()
    if t.status = 401 or t.status = 403
        Forget()
        StartPairing()
        return
    end if
    if not t.ok then return
    rows = []
    if type(t.json.rows) = "roArray" then rows = t.json.rows
    m.home.soft = true
    m.home.rows = rows
end sub

' ---- 62.6: navegação ----
sub Notice(text as string, secs as integer)
    m.top.removeChild(m.notice) ' volta para cima das telas empilhadas
    m.top.appendChild(m.notice)
    m.notice.text = text
    m.noticeTimer.control = "stop"
    if secs > 0 then m.noticeTimer.control = "start"
end sub

sub onNoticeEnd()
    m.notice.text = ""
end sub

function Current() as object
    if m.stack.Count() > 0 then return m.stack[m.stack.Count() - 1]
    return m.home
end function

sub Push(view as object)
    Current().visible = false
    m.top.appendChild(view)
    view.visible = true
    view.wantFocus = true
    m.stack.Push(view)
    m.notice.text = ""
end sub

sub Pop()
    view = m.stack.Pop()
    m.top.removeChild(view)
    cur = Current()
    cur.visible = true
    cur.wantFocus = true
    if m.homeStale or m.detStale then m.syncTimer.control = "start" ' 62.8: dá tempo de o player gravar a posição
end sub

sub ClearStack()
    while m.stack.Count() > 0
        m.top.removeChild(m.stack.Pop())
    end while
end sub

' Abre uma tela: movie, show, episode, season (id = série, n = temporada), collection, playlist, library.
sub Navigate(kind as string, id as integer, n as integer)
    if m.nav.busy = true then return
    m.nav = { busy: true, kind: kind, id: id, n: n }
    Notice(tr("nav_loading"), 0)
    base = m.server + "/api/tv/"
    if kind = "library"
        Request(base + "library/" + Str(id).Trim() + "/collections", "GET", "", AuthHeaders(), "onNavCols")
    else if kind = "mylist"
        Request(base + "mylist", "GET", "", AuthHeaders(), "onNav")
    else if kind = "season"
        Request(base + "show/" + Str(id).Trim() + "/season/" + Str(n).Trim(), "GET", "", AuthHeaders(), "onNav")
    else
        Request(base + kind + "/" + Str(id).Trim(), "GET", "", AuthHeaders(), "onNav")
    end if
end sub

sub NavFail(t as object)
    m.nav = {}
    if t.status = 401 or t.status = 403
        Forget()
        StartPairing()
    else
        Notice(tr("nav_fail"), 4)
    end if
end sub

sub onNavCols(event as object)
    t = event.getRoSGNode()
    m.cols = []
    if t.ok and type(t.json.items) = "roArray" then m.cols = t.json.items
    m.colCount = m.cols.Count()
    if t.status = 401 or t.status = 403
        NavFail(t)
        return
    end if
    Request(m.server + "/api/tv/library/" + Str(m.nav.id).Trim() + "?limit=200", "GET", "", AuthHeaders(), "onNav")
end sub

sub onNav(event as object)
    t = event.getRoSGNode()
    nav = m.nav
    m.nav = {}
    if not t.ok
        NavFail(t)
        return
    end if
    d = t.json
    kind = nav.kind
    if kind = "movie" or kind = "show" or kind = "episode"
        v = CreateObject("roSGNode", "DetailView")
        v.server = m.server
        v.imgToken = m.imgToken
        v.ref = { kind: kind, id: nav.id }
        v.data = d
        v.observeField("picked", "onPicked")
        Push(v)
    else if kind = "season"
        eps = []
        if type(d.episodes) = "roArray"
            for each e in d.episodes
                nm = JStr(e, "title")
                if nm = "" then nm = tr("det_play") + " " + Str(JInt(e, "episode", 0)).Trim()
                eps.Push({ type: "episode", id: JInt(e, "id", 0), title: nm, image: JStr(e, "image"), pct: JInt(e, "pct", 0), wide: true, season: JInt(e, "season", 0), episode: JInt(e, "episode", 0) })
            end for
        end if
        head = ""
        if type(d.show) = "roAssociativeArray" then head = JStr(d.show, "title")
        if nav.n = 0 then head = head + " — " + tr("det_special") else head = head + " — " + tr("det_season") + " " + Str(nav.n).Trim()
        PushGrid(head, eps, eps.Count())
    else if kind = "library"
        its = []
        for each c in m.cols
            its.Push(c)
        end for
        total = m.colCount
        if type(d.items) = "roArray"
            for each it in d.items
                its.Push(it)
            end for
        end if
        total = total + JInt(d, "total", 0)
        head = ""
        if type(d.library) = "roAssociativeArray" then head = JStr(d.library, "name")
        m.libId = nav.id
        PushGrid(head, its, total)
    else if kind = "mylist"
        its = []
        if type(d.items) = "roArray" then its = d.items
        PushGrid(tr("home_side_mylist"), its, its.Count())
    else
        its = []
        if type(d.items) = "roArray" then its = d.items
        PushGrid(JStr(d, "title"), its, its.Count())
    end if
end sub

' 62.7: abre o player por cima das telas; ao terminar ou sair (Voltar) ele avisa por `closed`.
sub PlayVideo(kind as string, id as integer, title as string)
    if id <= 0 or kind = "" then return
    v = CreateObject("roSGNode", "PlayerView")
    v.server = m.server
    v.token = m.token
    v.profile = m.profile
    v.imgToken = m.imgToken
    v.observeField("closed", "onPlayerClosed")
    v.media = { kind: kind, id: id, title: title }
    Push(v)
end sub

sub onPlayerClosed(event as object)
    m.homeStale = true ' o player gravou posição/assistido: Início e detalhe se atualizam
    m.detStale = true
    if m.stack.Count() > 0 and m.stack[m.stack.Count() - 1].isSameNode(event.getRoSGNode()) then Pop()
end sub

sub PushGrid(head as string, items as object, total as integer)
    v = CreateObject("roSGNode", "GridView")
    v.server = m.server
    v.imgToken = m.imgToken
    v.heading = head
    v.total = total
    v.items = items
    v.observeField("picked", "onPicked")
    v.observeField("more", "onGridMore")
    Push(v)
end sub

' Próxima página da biblioteca (offset conta só os itens da biblioteca, sem as coleções do começo).
sub onGridMore(event as object)
    m.moreView = event.getRoSGNode()
    off = event.getData() - m.colCount
    if off < 0 then off = 0
    Request(m.server + "/api/tv/library/" + Str(m.libId).Trim() + "?limit=200&offset=" + Str(off).Trim(), "GET", "", AuthHeaders(), "onLibMore")
end sub

sub onLibMore(event as object)
    t = event.getRoSGNode()
    if m.moreView = invalid then return
    its = []
    if t.ok and type(t.json.items) = "roArray" then its = t.json.items
    m.moreView.append = its ' vazio também libera o próximo pedido
end sub

' Card do Início/grade ou botão do detalhe escolhido.
sub onPicked(event as object)
    p = event.getData()
    if type(p) <> "roAssociativeArray" then return
    act = JStr(p, "act")
    if act = "play"
        PlayVideo(JStr(p, "kind"), JInt(p, "id", 0), JStr(p, "title"))
    else if act = "watched" or act = "mylist"
        DoAction(p)
    else if act = "season"
        Navigate("season", JInt(p, "show", 0), JInt(p, "n", 0))
    else if act = "episode"
        Navigate("episode", JInt(p, "id", 0), 0)
    else if act = "show"
        Navigate("show", JInt(p, "id", 0), 0)
    else if act = "related"
        its = []
        if type(p.items) = "roArray" then its = p.items
        PushGrid(JStr(p, "title"), its, its.Count())
    else
        k = JStr(p, "type") ' card de fileira/grade
        id = JInt(p, "id", 0)
        if k = "movie" or k = "show" or k = "episode" or k = "collection" or k = "playlist"
            Navigate(k, id, 0)
        else if k = "video"
            PlayVideo("movie", id, JStr(p, "title"))
        end if
    end if
end sub

' Busca os perfis da conta do token. forceList = mostrar a lista mesmo que já exista um perfil guardado (pareamento novo / trocar de perfil).
sub CheckToken(forceList as boolean)
    m.forceList = forceList
    Clear()
    m.state = "checking"
    m.title.text = tr("prof_loading")
    m.top.setFocus(true)
    LoadStrings("token")
end sub

sub ShowProfiles(err as string)
    Clear()
    m.state = "profiles"
    m.title.text = tr("prof_title")
    m.hint.text = tr("prof_hint")
    n = m.profiles.Count()
    m.status.color = "0xFF6B6BFF"
    m.status.text = err
    m.top.setFocus(true)
    if n = 0
        if err = "" then m.status.text = tr("prof_none")
        return
    end if
    content = CreateObject("roSGNode", "ContentNode")
    for each p in m.profiles
        item = content.CreateChild("ContentNode")
        item.title = JStr(p, "name")
        item.description = JStr(p, "avatar") ' cor quando não há foto
        item.hdPosterUrl = ImgUrl(m.server, m.imgToken, JStr(p, "photo"))
    end for
    cols = n
    if cols > 6 then cols = 6
    rows = Int((n + cols - 1) / cols)
    if rows > 2 then rows = 2
    m.profGrid.numColumns = cols
    m.profGrid.numRows = rows
    m.profGrid.translation = [Int((1920 - (cols * 260 - 20)) / 2), 400]
    m.profGrid.content = content
    m.profGrid.visible = true
    m.profGrid.setFocus(true)
    m.status.translation = [210, 880]
end sub

sub onProfileGrid()
    idx = m.profGrid.itemSelected
    if idx < 0 or idx >= m.profiles.Count() then return
    p = m.profiles[idx]
    m.wanted = { id: Str(Int(p.id)).Trim(), name: JStr(p, "name") }
    Clear()
    m.state = "checking"
    m.title.text = tr("prof_loading")
    m.top.setFocus(true)
    Request(m.server + "/api/tv/profile/" + m.wanted.id, "POST", "", { Authorization: "Bearer " + m.token }, "onProfilePick")
end sub

' Token de imagem do perfil em uso (X-Profile só quando já escolhido); depois segue para `after`: "profiles" ou "done".
sub GetImgToken(after as string)
    m.after = after
    h = { Authorization: "Bearer " + m.token }
    if after = "done" and m.profile <> "" then h["X-Profile"] = m.profile
    Request(m.server + "/api/tv/img-token", "GET", "", h, "onImgToken")
end sub

sub onImgToken(event as object)
    t = event.getRoSGNode()
    if t.status = 401 or t.status = 403
        Forget()
        StartPairing()
        return
    end if
    tok = JStr(t.json, "token")
    if t.ok and tok <> "" then m.imgToken = tok ' sem token as capas ficam em branco, o resto funciona
    if m.state <> "checking" then return
    if m.after = "profiles"
        ShowProfiles("")
    else
        LoadHome()
    end if
end sub

' Renovação silenciosa (a cada 3 h; o token vale de 6 a 12 h).
sub onImgTimer()
    if m.token = "" or m.server = "" then return
    h = { Authorization: "Bearer " + m.token }
    if m.profile <> "" then h["X-Profile"] = m.profile
    Request(m.server + "/api/tv/img-token", "GET", "", h, "onImgKeep")
end sub

sub onImgKeep(event as object)
    t = event.getRoSGNode()
    tok = JStr(t.json, "token")
    if t.ok and tok <> ""
        m.imgToken = tok
        if m.state = "home"
            m.home.imgToken = tok
            for each v in m.stack
                v.imgToken = tok
            end for
        end if
    end if
end sub

' ---- servidor ----
sub OpenKeyboard()
    dlg = CreateObject("roSGNode", "KeyboardDialog")
    dlg.title = tr("srv_dlg_title")
    dlg.message = tr("srv_dlg_msg")
    dlg.text = m.server
    dlg.buttons = [tr("btn_ok"), tr("btn_cancel")]
    dlg.observeField("buttonSelected", "onDlg")
    m.top.dialog = dlg
end sub

sub onDlg(event as object)
    dlg = event.getRoSGNode()
    idx = dlg.buttonSelected
    typed = dlg.text
    dlg.close = true
    if idx <> 0
        m.menu.setFocus(true)
        return
    end if
    addr = NormalizeServer(typed)
    if addr = ""
        m.menu.setFocus(true)
        return
    end if
    ConnectTo(addr)
end sub

sub onServerInfo(event as object)
    t = event.getRoSGNode()
    if t.ok and JStr(t.json, "app") = "starflix"
        m.server = m.pending
        StoreSet("server", m.server)
        StoreSet("server_name", JStr(t.json, "name"))
        StoreDelete("token")
        StoreDelete("device_id")
        m.token = ""
        StartPairing()
    else
        ShowServer(tr("srv_fail"))
    end if
end sub

sub onTokenCheck(event as object)
    t = event.getRoSGNode()
    if t.status = 401 or t.status = 403
        Forget()
        StartPairing()
        return
    end if
    if t.ok
        m.profiles = []
        if type(t.json.profiles) = "roArray" then m.profiles = t.json.profiles
        if not m.forceList and m.profile <> ""
            for each p in m.profiles
                if Str(Int(p.id)).Trim() = m.profile
                    m.profileName = JStr(p, "name")
                    StoreSet("profile_name", m.profileName)
                    GetImgToken("done")
                    return
                end if
            end for
        end if
        GetImgToken("profiles")
    else if not m.forceList and m.profile <> ""
        LoadHome() ' servidor fora do ar: tenta de novo com o perfil guardado
    else
        Clear()
        m.state = "retry"
        m.title.text = tr("pair_offline")
        m.retryTimer.control = "start"
    end if
end sub

sub onProfilePick(event as object)
    t = event.getRoSGNode()
    if t.status = 401 or t.status = 403
        Forget()
        StartPairing()
    else if t.ok
        m.profile = m.wanted.id
        m.profileName = m.wanted.name
        StoreSet("profile", m.profile)
        StoreSet("profile_name", m.profileName)
        GetImgToken("done")
    else
        ShowProfiles(tr("prof_fail"))
    end if
end sub

' ---- pareamento ----
sub onCode(event as object)
    if m.state <> "pair" then return
    t = event.getRoSGNode()
    code = JStr(t.json, "code")
    poll = JStr(t.json, "poll")
    if t.ok and code <> "" and poll <> ""
        m.poll = poll
        m.line1.text = tr("pair_step1")
        m.url.text = JStr(t.json, "url")
        m.line2.text = tr("pair_step2")
        m.code.text = Left(code, 3) + " " + Mid(code, 4)
        m.status.text = tr("pair_waiting")
        m.pollTimer.control = "start"
    else
        m.status.text = tr("pair_offline")
        m.retryTimer.control = "start"
    end if
end sub

sub onRetry()
    if m.state = "pair"
        StartPairing()
    else if m.state = "retry"
        CheckToken(m.forceList)
    else if m.state = "homeretry"
        LoadHome()
    end if
end sub

sub onPollTick()
    if m.state <> "pair" or m.polling or m.poll = "" then return
    m.polling = true
    Request(m.server + "/api/tv/code/" + m.poll, "GET", "", {}, "onPoll")
end sub

sub onPoll(event as object)
    m.polling = false
    if m.state <> "pair" then return
    t = event.getRoSGNode()
    st = JStr(t.json, "status")
    if st = "authorized"
        token = JStr(t.json, "token")
        if token <> ""
            m.token = token
            StoreSet("token", token)
            if t.json.DoesExist("device_id") then StoreSet("device_id", Str(Int(t.json.device_id)).Trim())
            m.profile = ""
            m.profileName = ""
            StoreDelete("profile")
            StoreDelete("profile_name")
            CheckToken(true)
            return
        end if
    end if
    if st = "expired" or st = "used" or st = "unknown" or t.status = 404 or t.status = 410
        StartPairing() ' código novo
    else if t.status < 0 or t.status >= 500
        m.status.text = tr("pair_offline")
    else
        m.status.text = tr("pair_waiting")
    end if
end sub

' ---- controle remoto: * (options) troca de servidor durante o pareamento ----
function onKeyEvent(key as string, press as boolean) as boolean
    if press and key = "back" and m.state = "home" and m.stack.Count() > 0
        Pop()
        return true
    end if
    if press and key = "options"
        if m.state = "pair"
            ShowServer("")
            return true
        else if m.state = "profiles"
            DoLogout()
            return true
        end if
    end if
    return false
end function

sub DoLogout()
    Request(m.server + "/api/tv/logout", "POST", "", { Authorization: "Bearer " + m.token }, "onLogout")
    Forget()
    StartPairing()
end sub

sub onLogout(event as object)
    ' a TV já esqueceu o token; se o servidor não respondeu, o aparelho sai da lista em Conectar uma TV (Revogar)
end sub
