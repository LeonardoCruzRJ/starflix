' 62.5: Início do canal — menu lateral (Início, bibliotecas, trocar de perfil, desconectar) + fileiras de /api/tv/home.
' MainScene preenche server, imgToken, profileName, libs e por último rows; `action` avisa "switch" ou "logout".
sub init()
    for each id in ["logo", "who", "side", "rows", "empty"]
        m[id] = m.top.findNode(id)
    end for
    Style(m.logo, 52, true)
    Style(m.who, 26, false)
    Style(m.empty, 34, false)
    m.logo.text = "StarFlix"
    m.actions = []
    m.rowData = []
    m.side.observeField("itemSelected", "onSide")
    m.rows.observeField("rowItemSelected", "onCard")
end sub

sub onRows()
    m.who.text = m.top.profileName
    if m.top.soft ' atualização silenciosa (62.8): mantém o menu e a posição nas fileiras
        m.top.soft = false
        hadFocus = m.rows.isInFocusChain()
        posn = m.rows.rowItemFocused
        BuildRows(m.top.rows)
        if m.rows.visible
            if type(posn) = "roArray" and posn.Count() = 2 and m.rowData.Count() > posn[0] and m.rowData[posn[0]].Count() > posn[1]
                m.rows.jumpToRowItem = posn
            end if
            if not hadFocus then m.side.setFocus(true)
        end if
        return
    end if
    BuildSide()
    BuildRows(m.top.rows)
end sub

sub BuildSide()
    content = CreateObject("roSGNode", "ContentNode")
    m.actions = []
    AddSide(content, tr("home_side_home"), { kind: "home" })
    AddSide(content, tr("home_side_search"), { kind: "search" })
    AddSide(content, tr("home_side_mylist"), { kind: "mylist" })
    for each l in m.top.libs
        AddSide(content, JStr(l, "name"), { kind: "library", id: JInt(l, "id", 0) })
    end for
    AddSide(content, tr("done_switch"), { kind: "switch" })
    AddSide(content, tr("done_logout"), { kind: "logout" })
    m.side.content = content
    n = m.actions.Count()
    if n > 12 then n = 12
    m.side.numRows = n
end sub

sub AddSide(content as object, label as string, act as object)
    item = content.CreateChild("ContentNode")
    item.title = label
    m.actions.Push(act)
end sub

sub BuildRows(rows as object)
    content = CreateObject("roSGNode", "ContentNode")
    sizes = []
    heights = []
    spacings = []
    labels = []
    offsets = []
    m.rowData = []
    for each r in rows
        items = r.items
        if type(items) = "roArray" and items.Count() > 0
            row = content.CreateChild("ContentNode")
            row.title = JStr(r, "title")
            m.rowData.Push(items)
            wide = false
            w = items[0].wide
            if type(w) = "roBoolean" then wide = w
            for each it in items
                c = row.CreateChild("ContentNode")
                c.title = JStr(it, "title")
                c.shortDescriptionLine = CardSub(it)
                path = JStr(it, "image")
                c.addFields({ imgPath: path, pct: JInt(it, "pct", 0) })
                c.hdPosterUrl = ImgUrl(m.top.server, m.top.imgToken, path)
            end for
            if wide
                sizes.Push([400, 300])
                heights.Push(300)
            else
                sizes.Push([200, 375])
                heights.Push(375)
            end if
            spacings.Push(80)
            labels.Push(true)
            offsets.Push([0, 14])
        end if
    end for
    n = sizes.Count()
    m.empty.text = ""
    if n = 0
        m.rows.visible = false
        m.empty.text = tr("home_empty")
        m.empty.visible = true
        m.side.setFocus(true)
        return
    end if
    m.empty.visible = false
    m.rows.rowItemSize = sizes
    m.rows.rowHeights = heights
    m.rows.rowSpacings = spacings
    m.rows.showRowLabel = labels
    m.rows.rowLabelOffset = offsets
    rowItemSpacing = []
    for i = 1 to n
        rowItemSpacing.Push([20, 0])
    end for
    m.rows.rowItemSpacing = rowItemSpacing
    m.rows.numRows = 2
    m.rows.content = content
    m.rows.visible = true
    m.rows.setFocus(true)
end sub

' Token de imagem renovado: reescreve a URL de todos os cards (os já carregados ficam no cache do aparelho).
sub onToken()
    c = m.rows.content
    if c = invalid then return
    for i = 0 to c.getChildCount() - 1
        row = c.getChild(i)
        for j = 0 to row.getChildCount() - 1
            it = row.getChild(j)
            if it.hasField("imgPath") then it.hdPosterUrl = ImgUrl(m.top.server, m.top.imgToken, it.imgPath)
        end for
    end for
end sub

sub onSide()
    idx = m.side.itemSelected
    if idx < 0 or idx >= m.actions.Count() then return
    k = m.actions[idx].kind
    if k = "home"
        if m.rows.visible
            m.rows.jumpToRowItem = [0, 0]
            m.rows.setFocus(true)
        end if
    else if k = "library"
        m.top.action = "library:" + Str(m.actions[idx].id).Trim()
    else
        m.top.action = k
    end if
end sub

sub onCard()
    rc = m.rows.rowItemSelected
    if type(rc) <> "roArray" or rc.Count() < 2 then return
    if rc[0] < 0 or rc[0] >= m.rowData.Count() then return
    items = m.rowData[rc[0]]
    if rc[1] < 0 or rc[1] >= items.Count() then return
    m.top.picked = items[rc[1]]
end sub

sub onWant()
    if m.rows.visible then m.rows.setFocus(true) else m.side.setFocus(true)
end sub

' Esquerda no início da fileira volta ao menu; direita no menu entra nas fileiras.
function onKeyEvent(key as string, press as boolean) as boolean
    if not press then return false
    if key = "left" and m.rows.isInFocusChain() and not m.side.isInFocusChain()
        m.side.setFocus(true)
        return true
    else if key = "right" and m.side.isInFocusChain() and m.rows.visible
        m.rows.setFocus(true)
        return true
    end if
    return false
end function
