#!/usr/bin/env pwsh
# SOC Seattle -- Avvio Probe Locale
# Usage:
#   .\start-probe.ps1              (usa immagine esistente o builda se manca)
#   .\start-probe.ps1 -Rebuild     (ribuilda sempre l'immagine)
#   .\start-probe.ps1 -Logs        (attacca i log al termine)
param(
    [switch]$Rebuild,
    [switch]$Logs
)

# -- Configurazione fissa
$SERVER_URL = "https://myscarlet.vercel.app"
$INTERFACE  = "wlan0"
$IMAGE      = "soc-probe"
$CONTAINER  = "soc-probe-local"

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
$REGISTRATION_TOKEN = Read-Host "  REGISTRATION_TOKEN (PRB-XXXXXXXXXXXX)"
$REGISTRATION_TOKEN = $REGISTRATION_TOKEN.Trim()

if (-not $REGISTRATION_TOKEN.StartsWith("PRB-") -or $REGISTRATION_TOKEN.Length -lt 16) {
    Err "Token non valido. Deve iniziare con PRB- e avere almeno 16 caratteri."
    exit 1
}
Ok "  Token accettato: $REGISTRATION_TOKEN"
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
# soc-probe-data e' un volume named persistente: sopravvive al rebuild del container.
# Se state.db esiste gia', l'agent si riautentica senza consumare il token.
$VOLUME = "soc-probe-data"
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
