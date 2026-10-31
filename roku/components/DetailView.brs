' 62.6: detalhes de filme, série e episódio (capa/frame, textos, botões). `picked`: {act: play|season|episode|show|related, ...}.
sub init()
    for each id in ["bd", "pic", "title", "meta", "rate", "over", "people", "tech", "btns"]
        m[id] = m.top.findNode(id)
    end for
    Style(m.title, 54, true)
    Style(m.meta, 28, false)
    Style(m.rate, 28, true)
    Style(m.over, 28, false)
    Style(m.people, 26, false)
    Style(m.tech, 24, false)
    m.acts = []
    m.btns.observeField("itemSelected", "onBtn")
end sub

sub onData()
    d = m.top.data
    m.d = d
    kind = JStr(d, "type")
    base = m.top.server
    tok = m.top.imgToken
    imgs = d.images
    parts = []
    if kind = "episode"
        m.pic.width = 560
        m.pic.height = 315
        m.pic.uri = ImgUrl(base, tok, JStr(d, "image"))
        m.title.text = JStr(d, "show")
        head = "T" + Str(JInt(d, "season", 0)).Trim() + " E" + Str(JInt(d, "episode", 0)).Trim()
        tt = JStr(d, "title")
        if tt <> "" then head = head + " · " + tt
        parts.Push(head)
        parts.Push(JStr(d, "air_date"))
        parts.Push(DurTxt(JInt(d, "duration", 0)))
    else
        m.pic.width = 320
        m.pic.height = 480
        m.pic.uri = ImgUrl(base, tok, JStr(imgs, "poster"))
        m.bd.uri = ImgUrl(base, tok, JStr(imgs, "backdrop"))
        m.title.text = JStr(d, "title")
        y = JInt(d, "year", 0)
        if y > 0 then parts.Push(Str(y).Trim())
        parts.Push(JStr(d, "content_rating"))
        parts.Push(DurTxt(JInt(d, "duration", 0)))
        if type(d.genres) = "roArray"
            g = []
            for each x in d.genres
                if GetInterface(x, "ifString") <> invalid then g.Push(x)
            end for
            parts.Push(JoinParts(g, ", "))
        end if
    end if
    m.meta.text = JoinParts(parts, "   ·   ")

    r = []
    n1 = NumTxt(d, "rating")
    if n1 <> "" then r.Push("TMDB " + n1)
    n2 = NumTxt(d, "imdb")
    if n2 <> "" then r.Push("IMDb " + n2)
    n3 = NumTxt(d, "rt")
    if n3 <> "" then r.Push("RT " + n3)
    m.rate.text = JoinParts(r, "   ·   ")
    m.over.text = JStr(d, "overview")

    lines = []
    if type(d.directors) = "roArray" and d.directors.Count() > 0
        names = []
        for each x in d.directors
            if GetInterface(x, "ifString") <> invalid then names.Push(x)
        end for
        lines.Push(tr("det_dir") + " " + JoinParts(names, ", "))
    end if
    if type(d.cast) = "roArray" and d.cast.Count() > 0
        names = []
        for each c in d.cast
            if names.Count() < 6 then names.Push(JStr(c, "name"))
        end for
        lines.Push(tr("det_cast") + " " + JoinParts(names, ", "))
    end if
    m.people.text = JoinParts(lines, Chr(10))
    t = []
    if type(d.tech) = "roArray"
        for each x in d.tech
            if GetInterface(x, "ifString") <> invalid then t.Push(x)
        end for
    end if
    m.tech.text = JoinParts(t, "   ·   ")
    idx = m.btns.itemFocused
    BuildButtons(d, kind)
    if idx > 0 and idx < m.acts.Count() then m.btns.jumpToItem = idx
end sub

' 62.8: o MainScene avisa o que mudou (assistido / Minha Lista) e os botões se refazem sem perder a posição.
sub onPatch()
    p = m.top.patch
    if type(p) <> "roAssociativeArray" or type(m.d) <> "roAssociativeArray" then return
    for each k in p
        m.d[k] = p[k]
    end for
    if p.DoesExist("watched") and p.watched = true then m.d.position = 0
    idx = m.btns.itemFocused
    BuildButtons(m.d, JStr(m.d, "type"))
    if idx > 0 and idx < m.acts.Count() then m.btns.jumpToItem = idx
end sub

' Assistido (filme/episódio) e Minha Lista (filme/série) logo depois do botão principal.
sub AddToggles(d as object, kind as string, labels as object)
    id = JInt(d, "id", 0)
    if kind <> "show"
        w = false
        if type(d.watched) = "roBoolean" then w = d.watched
        if w then labels.Push(tr("det_unwatched")) else labels.Push(tr("det_watched"))
        m.acts.Push({ act: "watched", kind: kind, id: id, value: not w })
    end if
    if kind <> "episode"
        l = false
        if type(d.in_list) = "roBoolean" then l = d.in_list
        if l then labels.Push(tr("det_list_del")) else labels.Push(tr("det_list_add"))
        m.acts.Push({ act: "mylist", id: id, value: not l })
    end if
end sub

sub BuildButtons(d as object, kind as string)
    labels = []
    m.acts = []
    if kind = "show"
        p = d.play
        if type(p) = "roAssociativeArray"
            se = "T" + Str(JInt(p, "season", 1)).Trim() + " E" + Str(JInt(p, "episode", 1)).Trim()
            nu = p.next_up
            if type(nu) = "roBoolean" and nu
                labels.Push(tr("det_continue") + " " + se)
            else
                labels.Push(tr("det_play") + " " + se)
            end if
            m.acts.Push({ act: "play", kind: "episode", id: JInt(p, "episode_id", 0), title: JStr(d, "title") + "  " + se })
        end if
        AddToggles(d, kind, labels)
        if type(d.seasons) = "roArray"
            for each s in d.seasons
                n = JInt(s, "n", 0)
                if n = 0 then lab = tr("det_special") else lab = tr("det_season") + " " + Str(n).Trim()
                lab = lab + "  (" + Str(JInt(s, "watched", 0)).Trim() + "/" + Str(JInt(s, "count", 0)).Trim() + ")"
                labels.Push(lab)
                m.acts.Push({ act: "season", show: JInt(d, "id", 0), n: n, title: JStr(d, "title") })
            end for
        end if
    else
        posn = JInt(d, "position", 0)
        if posn > 0 then labels.Push(tr("det_resume") + " " + ClockTxt(posn)) else labels.Push(tr("det_play"))
        if kind = "episode"
            m.acts.Push({ act: "play", kind: "episode", id: JInt(d, "id", 0), title: JStr(d, "show") + "  T" + Str(JInt(d, "season", 0)).Trim() + " E" + Str(JInt(d, "episode", 0)).Trim() })
        else
            m.acts.Push({ act: "play", kind: "movie", id: JInt(d, "id", 0), title: JStr(d, "title") })
        end if
        AddToggles(d, kind, labels)
    end if
    if kind = "episode"
        if JInt(d, "prev_id", -1) >= 0
            labels.Push(tr("det_prev"))
            m.acts.Push({ act: "episode", id: JInt(d, "prev_id", 0) })
        end if
        if JInt(d, "next_id", -1) >= 0
            labels.Push(tr("det_next"))
            m.acts.Push({ act: "episode", id: JInt(d, "next_id", 0) })
        end if
        labels.Push(tr("det_show"))
        m.acts.Push({ act: "show", id: JInt(d, "media_id", 0) })
    end if
    if type(d.related) = "roArray" and d.related.Count() > 0
        labels.Push(tr("det_related"))
        m.acts.Push({ act: "related", items: d.related, title: tr("det_related") + " — " + JStr(d, "title") })
    end if
    content = CreateObject("roSGNode", "ContentNode")
    for each l in labels
        c = content.CreateChild("ContentNode")
        c.title = l
    end for
    m.btns.content = content
    n = labels.Count()
    if n > 6 then n = 6
    if n < 1 then n = 1
    m.btns.numRows = n
end sub

sub onBtn()
    idx = m.btns.itemSelected
    if idx < 0 or idx >= m.acts.Count() then return
    m.top.picked = m.acts[idx]
end sub

sub onWant()
    m.btns.setFocus(true)
end sub

sub onToken()
    d = m.top.data
    if type(d) <> "roAssociativeArray" then return
    base = m.top.server
    tok = m.top.imgToken
    if JStr(d, "type") = "episode"
        m.pic.uri = ImgUrl(base, tok, JStr(d, "image"))
    else
        imgs = d.images
        m.pic.uri = ImgUrl(base, tok, JStr(imgs, "poster"))
        m.bd.uri = ImgUrl(base, tok, JStr(imgs, "backdrop"))
    end if
end sub
