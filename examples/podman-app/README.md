# Example: Podman single-container application

Build the package:

    python scripts/build-scarlet-package.py --source examples/podman-app --version 1.0.0 --output dist/

Upload `dist/customer-api-1.0.0.scarlet.tar.gz` in SCARLET (Packages → Upload).
The application `customer-api` must exist in SCARLET with runtime PODMAN (or DOCKER
in `allowed_runtimes`) and `allow_hooks` enabled if you keep the `hooks` section.
The manifest declares the secret `DB_PASSWORD`: configure it under
Applications → customer-api → Configuration before deploying, otherwise pre-flight fails.
