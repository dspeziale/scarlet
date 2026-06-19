#!/usr/bin/env bash
# SOC Seattle -- Avvio Probe Locale (Linux)
# Usage:
#   ./start-probe.sh              (usa immagine esistente o builda se manca)
#   ./start-probe.sh --rebuild    (ribuilda sempre l'immagine)
#   ./start-probe.sh --logs       (attacca i log al termine)
#   ./start-probe.sh --renew      (chiede un nuovo token e re-registra la sonda)
set -euo pipefail

# -- Configurazione fissa
SERVER_URL="https://myscarlet.vercel.app"
INTERFACE="wlan0"
IMAGE="soc-probe"
CONTAINER="soc-probe-local"
VOLUME="soc-probe-data"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOKEN_FILE="$SCRIPT_DIR/.probe-token"

# -- Flag
REBUILD=false
LOGS=false
RENEW=false
for arg in "$@"; do
    case "$arg" in
        --rebuild) REBUILD=true ;;
        --logs)    LOGS=true ;;
        --renew)   RENEW=true ;;
        *) echo "Opzione sconosciuta: $arg" >&2; exit 1 ;;
    esac
done

# -- Colori
info() { printf '\033[0;36m%s\033[0m\n' "$1"; }
ok()   { printf '\033[0;32m%s\033[0m\n' "$1"; }
warn() { printf '\033[0;33m%s\033[0m\n' "$1"; }
err()  { printf '\033[0;31m%s\033[0m\n' "$1" >&2; }

# -- Banner
info ""
info "  +--------------------------------------+"
info "  |  SOC Seattle - Probe Locale v1.0    |"
info "  +--------------------------------------+"
info ""
info "  Server    : $SERVER_URL"
info "  Interface : $INTERFACE"
info ""

# -- Verifica Docker
if ! command -v docker >/dev/null 2>&1; then
    err "Docker non trovato. Installa Docker e riprova."
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    err "Docker non in esecuzione (o permessi mancanti). Avvia il servizio docker e riprova."
    exit 1
fi

# -- Registration token
# La sonda persiste la propria identita' nel volume "$VOLUME" (state.db): una volta
# registrata si riautentica da sola senza riconsumare il token. Qui salviamo il token
# su disco al primo avvio cosi' negli avvii successivi non viene piu' richiesto.
read_valid_token() {
    local t
    while true; do
        read -r -p "  REGISTRATION_TOKEN (PRB-XXXXXXXXXXXX): " t
        t="$(echo "$t" | tr -d '[:space:]')"
        if [[ "$t" == PRB-* && ${#t} -ge 16 ]]; then
            REGISTRATION_TOKEN="$t"
            return 0
        fi
        err "  Token non valido. Deve iniziare con PRB- e avere almeno 16 caratteri."
    done
}

if $RENEW; then
    warn "  Rinnovo registrazione: la sonda verra' re-registrata con un nuovo token."
    read_valid_token
    printf '%s' "$REGISTRATION_TOKEN" > "$TOKEN_FILE"
    # Azzera l'identita' persistita cosi' l'agent esegue una registrazione pulita.
    if [ -n "$(docker volume ls -q --filter "name=^${VOLUME}$" 2>/dev/null)" ]; then
        warn "  Rimozione stato precedente (volume $VOLUME)..."
        docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
        docker volume rm "$VOLUME" >/dev/null 2>&1 || true
    fi
    ok "  Nuovo token salvato: $REGISTRATION_TOKEN"
elif [ -f "$TOKEN_FILE" ]; then
    REGISTRATION_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
    ok "  Token gia' presente (usa --renew per rinnovare la registrazione)."
else
    info "  Prima registrazione di questa sonda."
    read_valid_token
    printf '%s' "$REGISTRATION_TOKEN" > "$TOKEN_FILE"
    ok "  Token salvato: $REGISTRATION_TOKEN"
fi
info ""

# -- Stop container precedente
if [ -n "$(docker ps -aq --filter "name=^${CONTAINER}$" 2>/dev/null)" ]; then
    warn "  Rimozione container precedente ($CONTAINER)..."
    docker rm -f "$CONTAINER" >/dev/null
fi

# -- Build immagine
if $REBUILD || [ -z "$(docker images -q "$IMAGE" 2>/dev/null)" ]; then
    if $REBUILD; then
        warn "  Rebuild forzata (3-5 minuti)..."
    else
        warn "  Immagine non trovata - build iniziale (3-5 minuti)..."
    fi
    info ""
    docker build -t "$IMAGE" "$SCRIPT_DIR/probe"
    ok "  Immagine $IMAGE pronta."
    info ""
else
    ok "  Immagine $IMAGE gia presente (usa --rebuild per aggiornare)."
fi

# -- Avvio container
# $VOLUME e' un volume named persistente: sopravvive al rebuild del container.
# Se state.db esiste gia', l'agent si riautentica senza consumare il token.
info "  Avvio sonda..."
docker run -d \
    --name "$CONTAINER" \
    --cap-add NET_ADMIN \
    --cap-add NET_RAW \
    --network host \
    -v "${VOLUME}:/opt/agent/data" \
    -e "SERVER_URL=$SERVER_URL" \
    -e "REGISTRATION_TOKEN=$REGISTRATION_TOKEN" \
    -e "IDS_INTERFACE=$INTERFACE" \
    -e "AGENT_VERSION=1.0.0" \
    -e "HEARTBEAT_INTERVAL=30" \
    -e "TASK_POLL_INTERVAL=15" \
    -e "VERIFY_TLS=true" \
    --restart unless-stopped \
    "$IMAGE" >/dev/null

ok ""
ok "  [OK] Sonda avviata!"
info ""
info "  Comandi utili:"
info "    docker logs -f $CONTAINER"
info "    docker exec -it $CONTAINER bash"
info "    docker stop $CONTAINER"
info "    docker rm -f $CONTAINER"
info ""

# -- Log automatici
if $LOGS; then
    ok "  Log in tempo reale (Ctrl+C per uscire):"
    info ""
    docker logs -f "$CONTAINER"
else
    info "  Primi 30 log:"
    sleep 3
    docker logs --tail 30 "$CONTAINER"
    info ""
    info "  Per seguire i log: docker logs -f $CONTAINER"
fi
