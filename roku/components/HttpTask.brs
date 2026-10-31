' 62.1: uma chamada HTTP por tarefa (a Roku só faz rede fora da thread da tela). Crie, preencha e ponha control = "RUN".
' Resultado: json (objeto), ok (2xx) e, por último, status (código HTTP; -1 = sem resposta). Observe `status`.
sub init()
    m.top.functionName = "runTask"
end sub

sub runTask()
    req = CreateObject("roUrlTransfer")
    port = CreateObject("roMessagePort")
    req.SetMessagePort(port)
    url = m.top.url
    req.SetUrl(url)
    if Left(LCase(url), 5) = "https"
        req.SetCertificatesFile("common:/certs/ca-bundle.crt")
        req.InitClientCertificates()
    end if
    req.RetainBodyOnError(true)
    req.AddHeader("Accept", "application/json")
    req.AddHeader("Content-Type", "application/json")
    hd = m.top.headers
    if hd <> invalid
        for each k in hd
            req.AddHeader(k, hd[k])
        end for
    end if

    started = false
    method = UCase(m.top.method)
    if method = "POST"
        started = req.AsyncPostFromString(m.top.body)
    else if method = "DELETE"
        req.SetRequest("DELETE")
        started = req.AsyncPostFromString("")
    else
        started = req.AsyncGetToString()
    end if

    code = -1
    text = ""
    if started
        msg = Wait(m.top.timeout * 1000, port)
        if type(msg) = "roUrlEvent"
            code = msg.GetResponseCode()
            text = msg.GetString()
        else
            req.AsyncCancel()
        end if
    end if

    json = invalid
    if text <> "" then json = ParseJson(text)
    if type(json) <> "roAssociativeArray" then json = {}
    m.top.json = json
    m.top.ok = (code >= 200 and code < 300)
    m.top.status = code
end sub
