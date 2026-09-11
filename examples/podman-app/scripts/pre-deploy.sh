#!/bin/sh
# Runs on the target host before the new release is installed.
# Available variables: SCARLET_APPLICATION SCARLET_VERSION SCARLET_ENVIRONMENT
#                      SCARLET_RELEASE_DIR SCARLET_SHARED_DIR SCARLET_ENV_FILE SCARLET_HOOK
set -eu
echo "pre-deploy: preparing ${SCARLET_APPLICATION} ${SCARLET_VERSION} for ${SCARLET_ENVIRONMENT}"
mkdir -p "${SCARLET_SHARED_DIR}/data" "${SCARLET_SHARED_DIR}/logs"
