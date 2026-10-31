' 62.6: grade de cards (biblioteca, coleção, lista de reprodução, temporada, semelhantes). Cards de capa (8 colunas) ou 16:9 (4 colunas).
' MainScene preenche server, imgToken, heading, total e por último items; `picked` devolve o card escolhido; `more` pede a próxima página.
sub init()
    for each id in ["grid", "head", "empty"]
        m[id] = m.top.findNode(id)
    end for
    Style(m.head, 46, true)
    Style(m.empty, 34, false)
    m.cards = []
    m.loading = false
    m.grid.observeField("itemSelected", "onSel")
    m.grid.observeField("itemFocused", "onFoc")
end sub

sub onHeading()
    m.head.text = m.top.heading
end sub

sub onItems()
    items = m.top.items
    m.cards = []
    m.loading = false
    wide = false
    if items.Count() > 0
        w = items[0].wide
        if type(w) = "roBoolean" then wide = w
    end if
    if wide
        m.grid.itemSize = [400, 300]
        m.grid.numColumns = 4
        m.grid.translation = [130, 140]
    else
        m.grid.itemSize = [200, 375]
        m.grid.numColumns = 8
        m.grid.translation = [90, 140]
    end if
    content = CreateObject("roSGNode", "ContentNode")
    AddCards(content, items)
    m.grid.content = content
    m.empty.visible = (items.Count() = 0)
    m.empty.text = ""
    if items.Count() = 0 then m.empty.text = tr("grid_empty")
end sub

sub onAppend()
    m.loading = false
    items = m.top.append
    if items.Count() = 0 or m.grid.content = invalid then return
    AddCards(m.grid.content, items)
end sub

sub AddCards(content as object, items as object)
    for each it in items
        c = content.CreateChild("ContentNode")
        c.title = JStr(it, "title")
        c.shortDescriptionLine = CardSub(it)
        path = JStr(it, "image")
        c.addFields({ imgPath: path, pct: JInt(it, "pct", 0) })
        c.hdPosterUrl = ImgUrl(m.top.server, m.top.imgToken, path)
        m.cards.Push(it)
    end for
end sub

sub onSel()
    idx = m.grid.itemSelected
    if idx < 0 or idx >= m.cards.Count() then return
    m.top.picked = m.cards[idx]
end sub

' Perto do fim e ainda faltando itens: pede a próxima página (uma por vez).
sub onFoc()
    n = m.cards.Count()
    if m.loading or n >= m.top.total then return
    if m.grid.itemFocused >= n - 16
        m.loading = true
        m.top.more = n
    end if
end sub

sub onWant()
    m.grid.setFocus(true)
end sub

sub onToken()
    c = m.grid.content
    if c = invalid then return
    for i = 0 to c.getChildCount() - 1
        it = c.getChild(i)
        if it.hasField("imgPath") then it.hdPosterUrl = ImgUrl(m.top.server, m.top.imgToken, it.imgPath)
    end for
end sub
