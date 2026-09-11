#!/usr/bin/env bash
# Download front-end assets for offline/air-gapped installations (SCARLET_ASSET_MODE=local).
# Run once on a machine with internet access, then ship app/static/vendor with the image.
set -euo pipefail
cd "$(dirname "$0")/.."
V=app/static/vendor
mkdir -p $V/adminlte $V/bootstrap $V/bootstrap-icons/fonts $V/fontawesome/webfonts $V/chartjs $V/swagger

dl() { echo "  $2"; curl -fsSL "$1" -o "$2"; }

echo "[vendor] AdminLTE 4.3.1"
dl https://cdn.jsdelivr.net/npm/admin-lte@4.3.1/dist/css/adminlte.min.css $V/adminlte/adminlte.min.css
dl https://cdn.jsdelivr.net/npm/admin-lte@4.3.1/dist/js/adminlte.min.js   $V/adminlte/adminlte.min.js
echo "[vendor] Bootstrap 5.3.3"
dl https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js $V/bootstrap/bootstrap.bundle.min.js
echo "[vendor] Bootstrap Icons 1.11.3"
dl https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css $V/bootstrap-icons/bootstrap-icons.min.css
dl https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2 $V/bootstrap-icons/fonts/bootstrap-icons.woff2
dl https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff  $V/bootstrap-icons/fonts/bootstrap-icons.woff
echo "[vendor] Font Awesome 6.6.0"
dl https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.6.0/css/all.min.css $V/fontawesome/all.min.css
for f in fa-solid-900.woff2 fa-regular-400.woff2 fa-brands-400.woff2 fa-solid-900.ttf fa-regular-400.ttf fa-brands-400.ttf; do
  dl https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.6.0/webfonts/$f $V/fontawesome/webfonts/$f
done
echo "[vendor] Chart.js 4.4.4"
dl https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js $V/chartjs/chart.umd.min.js
echo "[vendor] Swagger UI 5.17.14"
dl https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css $V/swagger/swagger-ui.css
dl https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js $V/swagger/swagger-ui-bundle.js
echo "[vendor] done. Set SCARLET_ASSET_MODE=local."
