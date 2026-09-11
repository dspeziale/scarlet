#!/bin/sh
# Database migration hook. Must be idempotent: it runs on every deployment.
set -eu
echo "migrate: nothing to do for ${SCARLET_APPLICATION} ${SCARLET_VERSION}"
