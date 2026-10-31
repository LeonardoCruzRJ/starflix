' 62.5: um card do Início (RowList): capa 2:3 ou 16:9, barra de progresso, título e subtítulo; moldura dourada no foco.
sub init()
    for each id in ["ring", "ph", "pic", "track", "fill", "name", "sub"]
        m[id] = m.top.findNode(id)
    end for
    Style(m.name, 26, true)
    Style(m.sub, 22, false)
    m.pct = 0
end sub

sub onLayout()
    w = m.top.width
    h = m.top.height
    if w <= 0 or h <= 0 then return
    picH = h - 75 ' 75 px embaixo para título e subtítulo
    m.ring.width = w
    m.ring.height = picH
    for each n in [m.ph, m.pic]
        n.translation = [5, 5]
        n.width = w - 10
        n.height = picH - 10
    end for
    m.track.translation = [5, picH - 13]
    m.track.width = w - 10
    m.track.height = 8
    m.fill.translation = [5, picH - 13]
    m.fill.height = 8
    m.name.translation = [4, picH + 8]
    m.name.width = w - 8
    m.name.height = 34
    m.sub.translation = [4, picH + 42]
    m.sub.width = w - 8
    m.sub.height = 28
    ApplyPct()
end sub

sub onContent()
    c = m.top.itemContent
    if c = invalid then return
    m.name.text = c.title
    m.sub.text = c.shortDescriptionLine
    m.pic.uri = c.hdPosterUrl
    m.pct = 0
    if c.hasField("pct") then m.pct = c.pct
    ApplyPct()
end sub

sub ApplyPct()
    show = (m.pct > 0 and m.pct < 100 and m.top.width > 10)
    m.track.visible = show
    m.fill.visible = show
    if show then m.fill.width = Int((m.top.width - 10) * m.pct / 100)
end sub

sub onFocus()
    on = (m.top.focusPercent > 0.5 and (m.top.rowListHasFocus or m.top.gridHasFocus))
    if on then m.ring.color = "0xE5A00DFF" else m.ring.color = "0xE5A00D00"
    if on then m.name.color = "0xFFFFFFFF" else m.name.color = "0xD0D0D8FF"
end sub
