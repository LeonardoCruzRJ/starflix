' 62.7: player. Cadeia: GET /progress (retomada) -> GET /stream/../subs -> GET /api/tv/markers (episódio) -> POST /stream/../play (tv=1 + caps) -> Video.
' O Video manda `Authorization` e `X-Profile` em HttpHeaders; legendas .vtt vão por token curto (?it=) e deslocadas por ?shift= quando o HLS começa no meio.
sub init()
    for each id in ["vid", "skipBg", "skip", "info", "menuBg", "menu", "saveTimer"]
        m[id] = m.top.findNode(id)
    end for
    Style(m.skip, 30, true)
    Style(m.info, 36, false)
    m.tasks = {}
    m.tracks = []
    m.markers = []
    m.target = invalid
    m.offset = 0
    m.sid = ""
    m.safe = false
    m.retried = false
    m.finishing = false
    m.closed = false
    m.autoNext = true
    m.vid.observeField("state", "onState")
    m.vid.observeField("position", "onPos")
    m.menu.observeField("itemSelected", "onMenu")
    m.saveTimer.observeField("fire", "onSave")
end sub

function Hdr() as object
    h = { Authorization: "Bearer " + m.top.token }
    if m.top.profile <> "" then h["X-Profile"] = m.top.profile
    return h
end function

sub Req(path as string, method as string, body as string, cb as string)
    t = CreateObject("roSGNode", "HttpTask")
    t.url = m.top.server + path
    t.method = method
    t.body = body
    t.headers = Hdr()
    t.timeout = 100 ' o /play espera o 1º trecho do transcode (até 90 s)
    t.observeField("status", cb)
    m.tasks[cb] = t
    t.control = "RUN"
end sub

sub onMedia()
    md = m.top.media
    m.closed = false
    m.kind = JStr(md, "kind")
    m.id = JInt(md, "id", 0)
    m.title = JStr(md, "title")
    StartItem()
end sub

sub StartItem()
    m.vid.control = "stop"
    m.saveTimer.control = "stop"
    m.tracks = []
    m.markers = []
    m.offset = 0
    m.sid = ""
    m.safe = false
    m.retried = false
    m.finishing = false
    m.pos0 = 0
    HideSkip()
    m.menu.visible = false
    m.menuBg.visible = false
    m.info.text = m.title + Chr(10) + tr("nav_loading")
    Req("/progress/" + m.kind + "/" + Str(m.id).Trim(), "GET", "", "onProg")
end sub

sub onProg(event as object)
    if m.closed then return
    t = event.getRoSGNode()
    m.pos0 = 0
    seen = false
    w = t.json.watched
    if type(w) = "roBoolean" then seen = w
    if t.ok and not seen ' já assistido recomeça do início
        v = t.json.position
        if GetInterface(v, "ifFloat") <> invalid or GetInterface(v, "ifInt") <> invalid then m.pos0 = Int(v)
    end if
    Req("/stream/" + m.kind + "/" + Str(m.id).Trim() + "/subs", "GET", "", "onSubs")
end sub

sub onSubs(event as object)
    if m.closed then return
    t = event.getRoSGNode()
    m.subList = []
    if t.ok
        for each key in ["external", "embedded"]
            arr = t.json[key]
            if type(arr) = "roArray"
                for each s in arr
                    lang = JStr(s, "lang")
                    lab = JStr(s, "title")
                    if lab = "" then lab = lang
                    if lab = "" then lab = tr("sub_track")
                    m.subList.Push({ path: JStr(s, "url"), lang: lang, label: lab })
                end for
            end if
        end for
    end if
    if m.kind = "episode"
        Req("/api/tv/markers/" + Str(m.id).Trim(), "GET", "", "onMarkers")
    else
        DoPlay()
    end if
end sub

sub onMarkers(event as object)
    if m.closed then return
    t = event.getRoSGNode()
    if t.ok
        if type(t.json.markers) = "roArray" then m.markers = t.json.markers
        an = t.json.auto_next
        m.autoNext = true
        if type(an) = "roBoolean" then m.autoNext = an
    end if
    DoPlay()
end sub

sub DoPlay()
    ' capacidades da Roku (52.1): H.264/HEVC, AAC/AC3/EAC3, mp4/mkv/ts, 10 bits, SDR, até 5.1
    q = "/stream/" + m.kind + "/" + Str(m.id).Trim() + "/play?tv=1&caps=v%3Dh264.hevc%26a%3Daac.ac3.eac3%26c%3Dmp4.mkv.ts%26b10%3D1%26hdr%3D0%26ch%3D6"
    if m.pos0 > 5 then q = q + "&start=" + Str(m.pos0).Trim()
    if m.safe then q = q + "&mode=safe"
    Req(q, "POST", "", "onPlay")
end sub

sub onPlay(event as object)
    if m.closed then return
    t = event.getRoSGNode()
    if t.status = 401 or t.status = 403
        Fail(tr("nav_fail"))
        return
    end if
    url = JStr(t.json, "url")
    if not t.ok or url = ""
        Fail(tr("play_fail"))
        return
    end if
    m.offset = JInt(t.json, "offset", 0)
    m.sid = JStr(t.json, "sid")
    c = CreateObject("roSGNode", "ContentNode")
    c.url = ImgUrl(m.top.server, m.top.imgToken, url) ' 62.16: token curto na URL (o <video> do emulador web não manda HttpHeaders)
    c.title = m.title
    c.HttpHeaders = ["Authorization: Bearer " + m.top.token, "X-Profile: " + m.top.profile]
    fmt = "hls"
    if Instr(1, url, "/hls/") = 0 and Instr(1, url, "/dash/") = 0
        fmt = JStr(t.json, "container")
        if fmt = "" then fmt = "mp4"
        if m.pos0 > 5 then c.PlayStart = m.pos0 ' direct play: o servidor não corta, a Roku pula
    end if
    c.streamFormat = fmt
    shift = ""
    if m.offset > 0 then shift = "shift=" + Str(m.offset).Trim()
    subs = []
    m.tracks = []
    for each s in m.subList
        path = s.path
        if shift <> "" then path = path + "?" + shift
        lang = s.lang
        if Len(lang) < 2 then lang = "und"
        tr1 = { Language: lang, TrackName: ImgUrl(m.top.server, m.top.imgToken, path), Description: s.label }
        subs.Push(tr1)
        m.tracks.Push(tr1)
    end for
    if subs.Count() > 0 then c.SubtitleTracks = subs
    m.info.text = ""
    m.vid.content = c
    m.vid.globalCaptionMode = "Off"
    m.vid.control = "play"
    m.vid.setFocus(true)
    m.saveTimer.control = "start"
end sub

sub Fail(text as string)
    m.vid.control = "stop"
    m.info.text = m.title + Chr(10) + text
    m.top.setFocus(true)
end sub

' Posição real no arquivo (o HLS que começou no meio conta a partir de `offset`).
function RealPos() as integer
    return m.offset + Int(m.vid.position)
end function

sub onState()
    st = m.vid.state
    if st = "error"
        if not m.retried ' 52.3: falhou no direct/remux, tenta de novo em transcode completo, de onde parou
            m.retried = true
            m.safe = true
            m.pos0 = RealPos()
            m.info.text = m.title + Chr(10) + tr("nav_loading")
            DoPlay()
        else
            Fail(tr("play_fail"))
        end if
    else if st = "finished"
        Finish()
    end if
end sub

sub Finish()
    if m.finishing then return
    m.finishing = true
    m.saveTimer.control = "stop"
    dur = RealPos()
    if m.vid.duration > 0 then dur = m.offset + Int(m.vid.duration)
    Req("/progress/" + m.kind + "/" + Str(m.id).Trim(), "POST", FormatJson({ position: dur }), "onDone")
end sub

sub onDone(event as object)
    if m.closed then return
    t = event.getRoSGNode()
    nxt = invalid
    if t.ok then nxt = t.json["next"]
    if m.kind = "episode" and m.autoNext and type(nxt) = "roAssociativeArray" and JInt(nxt, "id", 0) > 0
        m.id = JInt(nxt, "id", 0)
        sn = "T" + Str(JInt(nxt, "season", 0)).Trim() + " E" + Str(JInt(nxt, "episode", 0)).Trim()
        if JStr(nxt, "title") <> "" then sn = sn + " · " + JStr(nxt, "title")
        m.title = sn
        StartItem()
    else
        Close()
    end if
end sub

sub onSave()
    if m.vid.state <> "playing" then return
    Req("/progress/" + m.kind + "/" + Str(m.id).Trim(), "POST", FormatJson({ position: RealPos() }), "onSaved")
end sub

sub onSaved(event as object)
end sub

sub Close()
    m.closed = true
    m.saveTimer.control = "stop"
    st = m.vid.state
    if (st = "playing" or st = "paused" or st = "buffering") and not m.finishing
        Req("/progress/" + m.kind + "/" + Str(m.id).Trim(), "POST", FormatJson({ position: RealPos() }), "onSaved")
    end if
    m.vid.control = "stop"
    if m.sid <> "" then Req("/stream/session/" + m.sid + "/stop", "POST", "", "onStopped")
    m.top.closed = "back"
end sub

sub onStopped(event as object)
end sub

' ---- pular abertura / créditos (marcadores do episódio) ----
sub onPos()
    if m.markers.Count() = 0 then return
    p = RealPos()
    for each mk in m.markers
        s = JNumF(mk, "start")
        e = JNumF(mk, "end")
        if p >= s and p < e - 1
            m.target = mk
            kind = JStr(mk, "kind")
            if kind = "credits" then m.skip.text = tr("skip_credits") else m.skip.text = tr("skip_intro")
            m.skip.visible = true
            m.skipBg.visible = true
            return
        end if
    end for
    HideSkip()
end sub

sub HideSkip()
    m.target = invalid
    m.skip.visible = false
    m.skipBg.visible = false
end sub

sub DoSkip()
    if m.target = invalid then return
    dest = JNumF(m.target, "end") - m.offset
    if dest < 0 then return
    m.vid.seek = dest
    HideSkip()
end sub

' ---- menu de legendas (tecla *) ----
sub ToggleMenu()
    if m.menu.visible
        CloseMenu()
        return
    end if
    content = CreateObject("roSGNode", "ContentNode")
    c0 = content.CreateChild("ContentNode")
    c0.title = tr("sub_off")
    for each t in m.tracks
        c = content.CreateChild("ContentNode")
        c.title = t.Description
    end for
    m.menu.content = content
    n = m.tracks.Count() + 1
    if n > 6 then n = 6
    m.menu.numRows = n
    m.menuBg.height = n * 56 + 40
    m.menuBg.visible = true
    m.menu.visible = true
    m.menu.setFocus(true)
end sub

sub CloseMenu()
    m.menu.visible = false
    m.menuBg.visible = false
    m.vid.setFocus(true)
end sub

sub onMenu()
    idx = m.menu.itemSelected
    if idx <= 0
        m.vid.globalCaptionMode = "Off"
    else if idx - 1 < m.tracks.Count()
        m.vid.subtitleTrack = m.tracks[idx - 1].TrackName
        m.vid.globalCaptionMode = "On"
    end if
    CloseMenu()
end sub

sub onWant()
    if m.vid.content <> invalid then m.vid.setFocus(true) else m.top.setFocus(true)
end sub

function onKeyEvent(key as string, press as boolean) as boolean
    if not press then return false
    if key = "back"
        if m.menu.visible
            CloseMenu()
        else
            Close()
        end if
        return true
    else if key = "options"
        ToggleMenu()
        return true
    else if key = "down" and m.target <> invalid and not m.menu.visible
        DoSkip()
        return true
    end if
    return false
end function
