' 62.4: um perfil na grade "Quem está assistindo?": foto pelo token de imagem; sem foto, quadrado na cor do perfil com a inicial.
sub init()
    m.ring = m.top.findNode("ring")
    m.bg = m.top.findNode("bg")
    m.initial = m.top.findNode("initial")
    m.pic = m.top.findNode("pic")
    m.name = m.top.findNode("name")
    Style(m.initial, 96, true)
    Style(m.name, 30, false)
end sub

sub onContent()
    c = m.top.itemContent
    if c = invalid then return
    m.name.text = c.title
    col = c.description ' cor do perfil (#rrggbb)
    if Len(col) = 7 and Left(col, 1) = "#" then m.bg.color = "0x" + Mid(col, 2) + "FF" else m.bg.color = "0xE5A00DFF"
    m.initial.text = UCase(Left(c.title, 1))
    m.initial.visible = (c.hdPosterUrl = "")
    m.pic.uri = c.hdPosterUrl
end sub

sub onFocus()
    if m.top.focusPercent > 0.5 then m.ring.color = "0xE5A00DFF" else m.ring.color = "0xE5A00D00"
end sub
