#!/bin/sh
# Runs after the health check succeeded (non critical: a failure is logged, not fatal).
set -eu
echo "post-deploy: ${SCARLET_APPLICATION} ${SCARLET_VERSION} is live on ${SCARLET_ENVIRONMENT}"
