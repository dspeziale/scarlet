#!/usr/bin/env pwsh
# SOC Seattle -- Avvio Probe Locale
# Usage:
#   .\start-probe.ps1              (usa immagine esistente o builda se manca)
#   .\start-probe.ps1 -Rebuild     (ribuilda sempre l'immagine)
#   .\start-probe.ps1 -Logs        (attacca i log al termine)
#   .\start-probe.ps1 -Renew       (chiede un nuovo token e re-registra la sonda)
param(
    [switch]$Rebuild,
    [switch]$Logs,
    [switch]$Renew
)

# -- Configurazione fissa
$SERVER_URL = "https://myscarlet.vercel.app"
$INTERFACE  = "wlan0"
$IMAGE      = "soc-probe"
$CONTAINER  = "soc-probe-local"
$VOLUME     = "soc-probe-data"
$TOKEN_FILE = Join-Path $PSScriptRoot ".probe-token"

# -- Colori
function Info { param($m) Write-Host $m -ForegroundColor Cyan }
function Ok   { param($m) Write-Host $m -ForegroundColor Green }
function Warn { param($m) Write-Host $m -ForegroundColor Yellow }
function Err  { param($m) Write-Host $m -ForegroundColor Red }

# -- Banner
Info ""
Info "  +--------------------------------------+"
Info "  |  SOC Seattle - Probe Locale v1.0    |"
Info "  +--------------------------------------+"
Info ""
Info "  Server    : $SERVER_URL"
Info "  Interface : $INTERFACE"
Info ""

# -- Verifica Docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Err "Docker non trovato. Installa Docker Desktop e riprova."
    exit 1
}
docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Err "Docker non in esecuzione. Avvia Docker Desktop e riprova."
    exit 1
}

# -- Registration token
# La sonda persiste la propria identita' nel volume "$VOLUME" (state.db): una volta
# registrata si riautentica da sola senza riconsumare il token. Qui salviamo il token
# su disco al primo avvio cosi' negli avvii successivi non viene piu' richiesto.
function Read-ValidToken {
    while ($true) {
        $t = (Read-Host "  REGISTRATION_TOKEN (PRB-XXXXXXXXXXXX)").Trim()
        if ($t.StartsWith("PRB-") -and $t.Length -ge 16) { return $t }
        Err "  Token non valido. Deve iniziare con PRB- e avere almeno 16 caratteri."
    }
}

if ($Renew) {
    Warn "  Rinnovo registrazione: la sonda verra' re-registrata con un nuovo token."
    $REGISTRATION_TOKEN = Read-ValidToken
    Set-Content -Path $TOKEN_FILE -Value $REGISTRATION_TOKEN -NoNewline
    # Azzera l'identita' persistita cosi' l'agent esegue una registrazione pulita.
    if (docker volume ls -q --filter "name=^${VOLUME}$" 2>$null) {
        Warn "  Rimozione stato precedente (volume $VOLUME)..."
        docker rm -f $CONTAINER 2>$null | Out-Null
        docker volume rm $VOLUME 2>$null | Out-Null
    }
    Ok "  Nuovo token salvato: $REGISTRATION_TOKEN"
}
elseif (Test-Path $TOKEN_FILE) {
    $REGISTRATION_TOKEN = (Get-Content -Path $TOKEN_FILE -Raw).Trim()
    Ok "  Token gia' presente (usa -Renew per rinnovare la registrazione)."
}
else {
    Info "  Prima registrazione di questa sonda."
    $REGISTRATION_TOKEN = Read-ValidToken
    Set-Content -Path $TOKEN_FILE -Value $REGISTRATION_TOKEN -NoNewline
    Ok "  Token salvato: $REGISTRATION_TOKEN"
}
Info ""

# -- Stop container precedente
$existing = docker ps -aq --filter "name=^${CONTAINER}$" 2>$null
if ($existing) {
    Warn "  Rimozione container precedente ($CONTAINER)..."
    docker rm -f $CONTAINER | Out-Null
}

# -- Build immagine
$imageExists = docker images -q $IMAGE 2>$null
if ($Rebuild -or -not $imageExists) {
    if ($Rebuild) {
        Warn "  Rebuild forzata (3-5 minuti)..."
    } else {
        Warn "  Immagine non trovata - build iniziale (3-5 minuti)..."
    }
    Info ""
    $probeDir = Join-Path $PSScriptRoot "probe"
    docker build -t $IMAGE $probeDir
    if ($LASTEXITCODE -ne 0) {
        Err "Build fallita. Controlla l output sopra."
        exit 1
    }
    Ok "  Immagine $IMAGE pronta."
    Info ""
} else {
    Ok "  Immagine $IMAGE gia presente (usa -Rebuild per aggiornare)."
}

# -- Avvio container
# $VOLUME e' un volume named persistente: sopravvive al rebuild del container.
# Se state.db esiste gia', l'agent si riautentica senza consumare il token.
Info "  Avvio sonda..."
docker run -d `
    --name $CONTAINER `
    --cap-add NET_ADMIN `
    --cap-add NET_RAW `
    --network host `
    -v "${VOLUME}:/opt/agent/data" `
    -e "SERVER_URL=$SERVER_URL" `
    -e "REGISTRATION_TOKEN=$REGISTRATION_TOKEN" `
    -e "IDS_INTERFACE=$INTERFACE" `
    -e "AGENT_VERSION=1.0.0" `
    -e "HEARTBEAT_INTERVAL=30" `
    -e "TASK_POLL_INTERVAL=15" `
    -e "VERIFY_TLS=true" `
    --restart unless-stopped `
    $IMAGE | Out-Null

if ($LASTEXITCODE -ne 0) {
    Err "Avvio fallito."
    exit 1
}

Ok ""
Ok "  [OK] Sonda avviata!"
Info ""
Info "  Comandi utili:"
Info "    docker logs -f $CONTAINER"
Info "    docker exec -it $CONTAINER bash"
Info "    docker stop $CONTAINER"
Info "    docker rm -f $CONTAINER"
Info ""

# -- Log automatici
if ($Logs) {
    Ok "  Log in tempo reale (Ctrl+C per uscire):"
    Info ""
    docker logs -f $CONTAINER
} else {
    Info "  Primi 30 log:"
    Start-Sleep 3
    docker logs --tail 30 $CONTAINER
    Info ""
    Info "  Per seguire i log: docker logs -f $CONTAINER"
}
