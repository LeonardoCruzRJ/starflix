' 62.2: procura servidores StarFlix na rede local. A Roku não faz mDNS; manda "STARFLIX_DISCOVER" por broadcast UDP (porta 32010)
' e cada servidor responde com um JSON {app, id, name, version, port}. O IP do servidor é o de quem respondeu.
' Resultado: found = [{ id, name, host, port }] sem repetir o mesmo servidor; done (por último).
sub init()
    m.top.functionName = "runTask"
end sub

sub runTask()
    found = []
    seen = {}
    port = CreateObject("roMessagePort")
    udp = CreateObject("roDatagramSocket")
    bound = false
    ' 62.13: o emulador (brs) não tem GetStatus nem UDP real; SetAddress falha lá e a descoberta é pulada (cai no endereço manual)
    if udp <> invalid and GetInterface(udp, "ifSocket") <> invalid
        udp.SetMessagePort(port)
        bound = TryBind(udp)
    end if
    if bound
        udp.SetBroadcast(true)
        dest = CreateObject("roSocketAddress")
        dest.SetAddress("255.255.255.255:32010")
        udp.SetSendToAddress(dest)
        udp.NotifyReadable(true)
        started = CreateObject("roTimespan")
        lastSend = -1000
        while started.TotalMilliseconds() < m.top.timeout * 1000
            if started.TotalMilliseconds() - lastSend >= 1000 ' reenvia a cada 1 s (UDP pode se perder)
                udp.SendStr("STARFLIX_DISCOVER")
                lastSend = started.TotalMilliseconds()
            end if
            msg = Wait(250, port)
            if type(msg) = "roSocketEvent" and udp.IsReadable()
                text = udp.ReceiveStr(1024)
                from = udp.GetReceivedFromAddress()
                info = ParseJson(text)
                if type(info) = "roAssociativeArray" and from <> invalid
                    addr = from.GetAddress()
                    colon = Instr(1, addr, ":")
                    if colon > 0 then addr = Left(addr, colon - 1)
                    id = JStr(info, "id")
                    if JStr(info, "app") = "starflix" and id <> "" and addr <> "" and not seen.DoesExist(id)
                        seen[id] = true
                        sport = 32000
                        if info.DoesExist("port") and GetInterface(info.port, "ifInt") <> invalid then sport = info.port
                        found.Push({ id: id, name: JStr(info, "name"), host: addr, port: sport })
                    end if
                end if
            end if
        end while
        udp.Close()
    end if
    m.top.found = found
    m.top.done = true
end sub

function TryBind(udp as object) as boolean
    for p = 32011 to 32016 ' porta local para ouvir as respostas
        local = CreateObject("roSocketAddress")
        local.SetAddress("0.0.0.0:" + Str(p).Trim())
        if udp.SetAddress(local) = true then return true ' SetAddress devolve false se a porta estiver ocupada (GetStatus não existe no emulador brs)
    end for
    return false
end function
