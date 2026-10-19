#!/usr/bin/env bash
# Generate a kubeconfig for the "pkm" ServiceAccount created by deploy/kubernetes/pkm-rbac.yaml.
#
#   ./make-kubeconfig.sh [-o /etc/pkm/kubeconfig] [--context NAME]
#
# Run it where kubectl works with administrative rights (e.g. a control-plane node).
# The resulting file contains a long-lived token: store it 0640 root:pkm and never commit it.
set -o errexit -o nounset -o pipefail

OUT=/etc/pkm/kubeconfig
CTX=""
NS=pkm-system
SA=pkm
SECRET=pkm-token
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o|--output) OUT="$2"; shift 2 ;;
    --context) CTX="$2"; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done
KC=(kubectl)
[[ -n "$CTX" ]] && KC+=(--context "$CTX")

command -v kubectl >/dev/null || { echo "kubectl not found" >&2; exit 1; }
"${KC[@]}" -n "$NS" get serviceaccount "$SA" >/dev/null \
  || { echo "ServiceAccount $NS/$SA not found: kubectl apply -f deploy/kubernetes/pkm-rbac.yaml" >&2; exit 1; }

TOKEN=""
for _ in $(seq 1 20); do
  TOKEN="$("${KC[@]}" -n "$NS" get secret "$SECRET" -o jsonpath='{.data.token}' 2>/dev/null | base64 -d || true)"
  [[ -n "$TOKEN" ]] && break
  sleep 1
done
[[ -n "$TOKEN" ]] || { echo "token not available in secret $NS/$SECRET" >&2; exit 1; }

CLUSTER="$("${KC[@]}" config view --minify -o jsonpath='{.clusters[0].name}')"
SERVER="$("${KC[@]}" config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
CA="$("${KC[@]}" config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')"
if [[ -z "$CA" ]]; then
  CA="$("${KC[@]}" -n "$NS" get secret "$SECRET" -o jsonpath='{.data.ca\.crt}')"
fi

umask 027
TMP="$(mktemp)"
cat > "$TMP" <<EOF
apiVersion: v1
kind: Config
clusters:
- name: $CLUSTER
  cluster:
    server: $SERVER
    certificate-authority-data: $CA
users:
- name: pkm
  user:
    token: $TOKEN
contexts:
- name: pkm@$CLUSTER
  context:
    cluster: $CLUSTER
    user: pkm
current-context: pkm@$CLUSTER
EOF
install -m 0640 "$TMP" "$OUT"
rm -f "$TMP"
if getent group pkm >/dev/null && [[ $(id -u) -eq 0 ]]; then chown root:pkm "$OUT"; fi
echo "kubeconfig written to $OUT (context pkm@$CLUSTER, server $SERVER)"
echo "test: kubectl --kubeconfig $OUT get nodes"
