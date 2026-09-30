"""Errori ed exit code di appctl (documentati in docs/OPERATIONS.md)."""

from __future__ import annotations

EXIT_OK = 0
EXIT_FAILURE = 1  # errore generico
EXIT_USAGE = 2  # uso errato o configurazione non valida
EXIT_REGISTRY = 3  # registry non raggiungibile o immagine inesistente
EXIT_DEPLOY_ROLLED_BACK = 4  # deploy fallito, versione precedente ripristinata e sana
EXIT_LOCKED = 5  # un'altra operazione appctl e' in corso
EXIT_DOCKER = 6  # Docker non disponibile
EXIT_DEPLOY_DOWN = 7  # deploy fallito E rollback fallito: applicazione non disponibile
EXIT_MIGRATION = 8  # migrazione DB fallita, versione precedente ancora in esecuzione
EXIT_UNHEALTHY = 9  # health check fallito (appctl health)

EXIT_DESCRIPTIONS = {
    EXIT_OK: "operazione riuscita",
    EXIT_FAILURE: "errore generico",
    EXIT_USAGE: "uso errato o configurazione non valida",
    EXIT_REGISTRY: "registry non raggiungibile o immagine inesistente",
    EXIT_DEPLOY_ROLLED_BACK: "deploy fallito, rollback automatico riuscito",
    EXIT_LOCKED: "un'altra operazione appctl e' in corso",
    EXIT_DOCKER: "Docker non disponibile",
    EXIT_DEPLOY_DOWN: "deploy fallito e rollback fallito: APPLICAZIONE NON DISPONIBILE",
    EXIT_MIGRATION: "migrazione database fallita, versione precedente ancora attiva",
    EXIT_UNHEALTHY: "applicazione non sana",
}


class AppctlError(Exception):
    """Errore operativo con exit code e messaggio comprensibile all'operatore."""

    def __init__(self, message: str, exit_code: int = EXIT_FAILURE, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.hint = hint


class UsageError(AppctlError):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message, EXIT_USAGE, hint)


class DockerUnavailableError(AppctlError):
    def __init__(self, message: str = "Docker non raggiungibile", hint: str | None = None):
        super().__init__(
            message,
            EXIT_DOCKER,
            hint or "verificare con: systemctl status docker  (oppure appctl doctor)",
        )


class RegistryError(AppctlError):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message, EXIT_REGISTRY, hint)


class LockedError(AppctlError):
    def __init__(self, holder: str):
        super().__init__(
            f"un'altra operazione appctl e' in corso ({holder})",
            EXIT_LOCKED,
            "attendere il termine oppure verificare con: appctl history",
        )
