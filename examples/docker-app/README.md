# Example: Docker Compose application

    python scripts/build-scarlet-package.py --source examples/docker-app --version 1.0.0 --output dist/

SCARLET runs on the target:

    docker compose --project-name billing-worker --file <release>/docker-compose.yml --env-file <shared>/config/scarlet.env up -d

The `container_name` of the main service must equal the application code so that
status/logs/health work; the same package also works on Podman 4.1+ (`podman compose`).
