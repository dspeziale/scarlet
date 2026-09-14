#!/usr/bin/env python3
"""Manuale PDF: architettura e funzionamento di SCARLET.

Composto in PT Sans Narrow. Il contenuto segue docs/architecture.md, docs/security.md,
app/deployment/planner.py, app/models/enums.py e app/ssh/command.py.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdflib as P  # noqa: E402
from pdflib import b, c  # noqa: E402

VERSION = "SCARLET 1.0.0"
LIGHT_RED = P.colors.HexColor("#fdf3f4")
LIGHT_BLUE = P.colors.HexColor("#eef3f9")
LIGHT_GREEN = P.colors.HexColor("#edf6f0")


# --- figure ---------------------------------------------------------------------------------


def fig_control_plane() -> P.Diagram:
    """Il concetto centrale: due stati a confronto e la divergenza fra loro."""
    d = P.Diagram(174, 74)

    d.box(
        6,
        44,
        62,
        22,
        "Stato desiderato",
        [
            "chi: gli operatori, attraverso",
            "deployment e operazioni",
            "versione · avviata/ferma · repliche",
        ],
        stroke=P.RED,
        fill=LIGHT_RED,
    )

    d.box(
        106,
        44,
        62,
        22,
        "Stato effettivo",
        [
            "chi: il motore di deployment,",
            "le operazioni, il riconciliatore",
            "versione · stato · salute · runtime",
        ],
        stroke=P.colors.HexColor("#1d4f7a"),
        fill=LIGHT_BLUE,
    )

    d.box(
        56,
        12,
        62,
        20,
        "Divergenza (drift)",
        [
            "compute_drift(desiderato, effettivo)",
            "VERSION · STATE · UNEXPECTED_STOP",
            "MISSING · RUNTIME",
        ],
        stroke=P.colors.HexColor("#8a6100"),
        fill=P.colors.HexColor("#fdf6e8"),
    )

    d.arrow((68, 55), (106, 55), "", color=P.RED)
    d.label(87, 57.5, "il motore allinea", size=7, color=P.RED, anchor="middle", bold=True)
    d.label(87, 70, "l'effettivo al desiderato", size=7, color=P.RED, anchor="middle", bold=True)
    d.arrow((37, 44), (70, 32), "", color=P.MUTED)
    d.arrow((137, 44), (104, 32), "", color=P.MUTED)
    d.label(
        87,
        6,
        "il riconciliatore osserva e segnala; rimedia solo in DEV e solo se abilitato",
        size=7.4,
        color=P.MUTED,
        anchor="middle",
    )
    d.label(87, 38, "confronto", size=7, color=P.MUTED, anchor="middle")
    return d


def fig_componenti() -> P.Diagram:
    """I processi che compongono il control plane e i loro collegamenti."""
    d = P.Diagram(174, 100)

    d.box(34, 88, 62, 10, "Browser degli operatori", [], fill=P.PANEL)

    d.group(0, 16, 174, 68, "SERVER SCARLET — rete interna dei container")
    d.box(34, 64, 62, 11, "nginx", ["TLS · redirect 80 › 443"], fill=P.colors.white)
    d.box(
        34,
        46,
        62,
        14,
        "gunicorn (web)",
        ["Flask: console e API", "autorizzazioni, audit"],
        stroke=P.RED,
        fill=LIGHT_RED,
    )
    d.box(
        34,
        26,
        62,
        14,
        "worker Celery",
        ["deployment, operazioni,", "discover, riconciliazione"],
        stroke=P.RED,
        fill=LIGHT_RED,
    )
    d.box(4, 26, 26, 14, "beat", ["calendario"], fill=P.colors.white, title_size=8)
    d.box(110, 64, 60, 11, "PostgreSQL 16", ["stato · piani · audit"], fill=P.PANEL)
    d.box(110, 44, 60, 13, "Redis 7", ["coda dei job · lock"], fill=P.PANEL)
    d.box(110, 24, 60, 13, "Volume artefatti", ["pacchetti di rilascio"], fill=P.PANEL)

    d.box(20, 0, 60, 13, "Host di destinazione", ["podman / docker / kubectl"], fill=P.PANEL)
    d.box(94, 0, 60, 13, "Host di destinazione", ["podman / docker / kubectl"], fill=P.PANEL)

    d.arrow((65, 88), (65, 75), "HTTPS")
    d.arrow((65, 64), (65, 60), "")
    d.arrow((96, 53), (110, 66), "", color=P.MUTED)
    d.arrow((96, 50), (110, 50), "coda", color=P.MUTED, label_dy=0.8)
    d.arrow((110, 46), (96, 35), "job", color=P.MUTED, label_dy=0.8)
    d.arrow((96, 30), (110, 30), "", color=P.MUTED)
    d.arrow((30, 33), (34, 33), "", color=P.MUTED)
    d.arrow((50, 26), (50, 13), "SSH 22", color=P.RED)
    d.arrow((80, 26), (124, 13), "SSH 22", color=P.RED, label_dy=1.6)
    return d


def fig_livelli() -> P.Diagram:
    """La pila dei livelli: ogni strato parla solo con quello sotto."""
    d = P.Diagram(174, 96)
    rows = [
        (
            "Rotte Flask",
            "app/api e app/web: HTTP, autenticazione, forma dei dati. Nessuna logica di business.",
            P.colors.white,
        ),
        (
            "Servizi",
            "DeploymentService, LifecycleService, HostService, PackageService, PreflightService, ReconciliationService: autorizzazioni e guardia di produzione.",
            LIGHT_RED,
        ),
        (
            "Motore di deployment",
            "oggetti di dominio, pianificatore, macchina a stati, passi, rollback, contratto del manifest, validatore del pacchetto, archivio artefatti, layout remoto.",
            LIGHT_RED,
        ),
        (
            "Adattatori di runtime",
            "interfaccia RuntimeAdapter con le implementazioni Docker, Podman e Kubernetes. Non conoscono Flask.",
            LIGHT_BLUE,
        ),
        (
            "Livello SSH",
            "RemoteCommand (argv e allow-list), client Paramiko con chiavi host rigide, trasferimento SFTP, client falso per i test.",
            LIGHT_BLUE,
        ),
        (
            "Host di destinazione",
            "il layout sotto /opt/scarlet e il runtime dei container.",
            P.PANEL,
        ),
    ]
    y = 82
    for title, desc, fill in rows:
        d.box(0, y, 74, 13, title, [], fill=fill, title_size=9)
        d.text_block(79, y + 9, 95, desc, size=6.9, leading=3.3)
        if y > 8:
            d.arrow((37, y), (37, y - 2.6), "", color=P.DARK)
        y -= 15.5
    d.text_block(
        0,
        2,
        174,
        "Trasversali a tutti i livelli: sicurezza (cifratura, permessi, validatori, guardia di produzione), audit in sola aggiunta, lock distribuiti, job Celery, repository e modelli.",
        size=6.9,
    )
    return d


def fig_pipeline() -> P.Diagram:
    """I passi di un rilascio, con il punto di non ritorno e il ramo di rollback."""
    d = P.Diagram(174, 66)
    first = [
        "validate",
        "preflight",
        "prepare",
        "transfer",
        "verify",
        "extract",
        "configure",
        "install",
    ]
    for i, name in enumerate(first):
        x = i * 21.8
        d.box(x, 48, 19.5, 13, name, [], fill=P.colors.white, title_size=7.4)
        d.label(x + 9.75, 62.5, str(i + 1), size=6.4, color=P.MUTED, anchor="middle")
        if i:
            d.arrow((x - 2.3, 54.5), (x, 54.5), "", color=P.DARK)
    d.arrow((165, 48), (165, 44), "", color=P.DARK)
    d.arrow((165, 44), (10, 44), "", color=P.DARK)
    d.arrow((10, 44), (10, 36), "", color=P.DARK)

    second = ["activate", "start", "health", "finalize", "cleanup"]
    for i, name in enumerate(second):
        x = i * 33
        critico = name in ("activate", "start", "health")
        d.box(
            x,
            22,
            30,
            13,
            name,
            [],
            fill=LIGHT_RED if critico else P.colors.white,
            stroke=P.RED if critico else P.DARK,
            title_size=7.8,
        )
        d.label(x + 15, 36.5, str(i + 9), size=6.4, color=P.MUTED, anchor="middle")
        if i:
            d.arrow((x - 3, 28.5), (x, 28.5), "", color=P.DARK)

    d.label(
        0,
        16.5,
        "punto di non ritorno: da qui in poi un errore attiva il rollback automatico",
        size=7,
        color=P.RED,
        bold=True,
    )
    d.arrow((81, 22), (81, 10), "errore", color=P.RED, label_dy=0)
    d.arrow((81, 10), (112, 10), "", color=P.RED)
    d.box(
        112,
        4,
        60,
        12,
        "ROLLING_BACK › ROLLED_BACK",
        ["ripristina la release precedente"],
        stroke=P.RED,
        fill=LIGHT_RED,
        title_size=7.6,
    )
    return d


def fig_attivazione() -> P.Diagram:
    """Lo scambio del symlink: prima e dopo, in un solo passaggio atomico."""
    d = P.Diagram(174, 56)
    d.label(0, 52, "PRIMA", size=8, color=P.MUTED, bold=True)
    d.box(0, 30, 40, 11, "current", ["symlink"], stroke=P.RED, fill=LIGHT_RED, title_size=8)
    d.box(48, 36, 32, 10, "releases/2.4.0", [], fill=P.PANEL, title_size=7.6)
    d.box(
        48, 20, 32, 10, "releases/2.5.0", ["appena estratta"], fill=P.colors.white, title_size=7.6
    )
    d.arrow((40, 35.5), (48, 41), "", color=P.RED)

    d.label(92, 52, "DOPO", size=8, color=P.MUTED, bold=True)
    d.box(92, 30, 40, 11, "current", ["symlink"], stroke=P.RED, fill=LIGHT_RED, title_size=8)
    d.box(136, 36, 32, 10, "releases/2.4.0", ["conservata"], fill=P.PANEL, title_size=7.6)
    d.box(
        136, 20, 32, 10, "releases/2.5.0", ["attiva"], stroke=P.RED, fill=LIGHT_RED, title_size=7.6
    )
    d.arrow((132, 35.5), (136, 25), "", color=P.RED)

    d.label(
        87,
        12,
        "ln -sfn ... current.tmp  &&  mv -T ... current.tmp current",
        size=7.6,
        color=P.INK,
        anchor="middle",
    )
    d.label(
        87,
        6,
        "il rename è atomico: non esiste un istante in cui current non punta a una release valida",
        size=7,
        color=P.MUTED,
        anchor="middle",
    )
    d.label(
        87,
        0.5,
        "il rollback è lo stesso gesto in senso opposto, e la release precedente è già sull'host",
        size=7,
        color=P.MUTED,
        anchor="middle",
    )
    return d


def fig_riconciliazione() -> P.Diagram:
    """Il ciclo osserva, confronta, segnala."""
    d = P.Diagram(174, 50)
    d.box(2, 30, 40, 15, "beat", ["ogni 5 minuti", "(configurabile)"], fill=P.colors.white)
    d.box(
        52,
        30,
        44,
        15,
        "reconcile_host",
        ["interroga il runtime", "via SSH"],
        fill=LIGHT_RED,
        stroke=P.RED,
    )
    d.box(106, 30, 44, 15, "ActualApplicationState", ["versione, stato, salute"], fill=LIGHT_BLUE)
    d.box(
        52,
        4,
        44,
        15,
        "DriftReport",
        ["tipo e dettaglio", "salvato sull'istanza"],
        fill=P.colors.HexColor("#fdf6e8"),
    )
    d.box(
        106,
        4,
        44,
        15,
        "Notifica e cruscotto",
        ["divergenza visibile", "agli operatori"],
        fill=P.colors.white,
    )
    d.arrow((42, 37.5), (52, 37.5), "")
    d.arrow((96, 37.5), (106, 37.5), "")
    d.arrow((128, 30), (96, 19), "confronto con il desiderato", color=P.MUTED, label_dy=1.6)
    d.arrow((96, 11.5), (106, 11.5), "")
    d.arrow((74, 19), (74, 30), "rimedio: solo DEV, opzionale", color=P.MUTED, dashed=True)
    return d


def fig_comando() -> P.Diagram:
    """Come nasce un comando remoto: nessuna stringa costruita a mano."""
    d = P.Diagram(174, 40)
    boxes = [
        (0, 32, "Adattatore", ["costruisce argv", "come lista"]),
        (37, 32, "RemoteCommand", ["argv[0] nella", "allow-list"]),
        (74, 32, "Validatori", ["percorsi sotto", "la base, regex"]),
        (111, 32, "shlex.quote", ["ogni argomento", "viene protetto"]),
        (148, 26, "SSH", ["canale", "dedicato"]),
    ]
    for x, w, title, lines in boxes:
        d.box(x, 14, w, 18, title, lines, fill=P.colors.white, title_size=8)
    for x in (32, 69, 106, 143):
        d.arrow((x, 23), (x + 5, 23), "", color=P.DARK)
    d.label(
        87,
        8,
        "non esiste una funzione 'esegui questo comando': la shell non viene mai invocata con testo libero",
        size=7.4,
        color=P.RED,
        anchor="middle",
        bold=True,
    )
    d.label(
        87,
        3,
        "timeout obbligatorio · stdout, stderr, codice di uscita e durata registrati · output ripulito prima del salvataggio",
        size=7,
        color=P.MUTED,
        anchor="middle",
    )
    return d


# --- contenuto -------------------------------------------------------------------------------


def story() -> list:
    s: list = []

    s += P.toc(
        [
            (1, "1. SCARLET in una pagina", "c1"),
            (1, "2. Il modello: un control plane", "c2"),
            (2, "Stato desiderato, stato effettivo, divergenza", "c2"),
            (1, "3. Componenti e topologia", "c3"),
            (1, "4. I livelli del software", "c4"),
            (1, "5. Gli oggetti di dominio", "c5"),
            (1, "6. Anatomia di un rilascio", "c6"),
            (2, "Dal wizard alla coda", "c6"),
            (2, "I tredici passi del piano", "c6"),
            (2, "La macchina a stati", "c6"),
            (1, "7. Attivazione atomica e rollback", "c7"),
            (1, "8. Adattatori di runtime", "c8"),
            (1, "9. Il contratto del pacchetto", "c9"),
            (1, "10. Sicurezza per progetto", "c10"),
            (2, "Come nasce un comando remoto", "c10"),
            (2, "Controlli sulla produzione", "c10"),
            (1, "11. Riconciliazione e divergenza", "c11"),
            (1, "12. Job asincroni, code e lock", "c12"),
            (1, "13. Modello dei dati", "c13"),
            (1, "14. Osservabilità e tracciabilità", "c14"),
            (1, "15. Punti di estensione", "c15"),
        ]
    )

    # ============================= 1
    s += P.section("1. SCARLET in una pagina", "c1")
    s += [
        P.para(
            "SCARLET gestisce il ciclo di vita delle applicazioni su server Oracle Linux remoti: le installa, "
            "le avvia, le ferma, le aggiorna, le riporta alla versione precedente e ne sorveglia lo stato. "
            "Lo fa via SSH, senza installare nulla sui server gestiti.",
            "lead",
        ),
        P.para(
            "La differenza rispetto a uno script di deploy sta in una scelta di fondo: SCARLET non è un "
            "esecutore di comandi, è un "
            + b("control plane")
            + ". Per ogni coppia applicazione-server "
            "conserva due fotografie, quella che gli operatori hanno chiesto e quella osservata sul campo, e "
            "il suo compito è ridurre la distanza fra le due. Tutto il resto, dalla pianificazione dei passi "
            "alla gestione degli errori, discende da qui."
        ),
        P.space(4),
        P.table(
            [
                ["Principio", "Come si traduce nel codice"],
                [
                    b("Stato dichiarato, non comandi"),
                    "ogni istanza applicativa ha uno stato desiderato e uno effettivo; il motore calcola i passi necessari per allinearli",
                ],
                [
                    b("Un solo modo di raggiungere l'host"),
                    "tutto passa dal livello SSH, che accetta solo liste di argomenti con eseguibile in allow-list; non esiste una funzione per eseguire testo libero",
                ],
                [
                    b("Piano prima dell'esecuzione"),
                    "il pianificatore produce un "
                    + c("DeploymentPlan")
                    + " salvato nel database; l'esecuzione registra ogni passo, quindi è ricostruibile a posteriori",
                ],
                [
                    b("Il runtime è un dettaglio"),
                    "Docker, Podman e Kubernetes stanno dietro la stessa interfaccia; aggiungerne uno significa scrivere una classe, non toccare il motore",
                ],
                [
                    b("La produzione si difende da sola"),
                    "permessi dedicati, frase da digitare, motivazione obbligatoria, approvazione di una seconda persona, lock per applicazione e host",
                ],
                [
                    b("Tutto lascia traccia"),
                    "audit in sola aggiunta, eventi di sicurezza, identificativo di richiesta propagato dal browser fino al comando remoto",
                ],
            ],
            [26, 74],
        ),
        P.space(8),
        fig_control_plane(),
        P.caption("Figura 1 — I due stati e la divergenza fra loro: è il cuore del modello."),
    ]

    # ============================= 2
    s += P.section("2. Il modello: un control plane", "c2")
    s += [
        P.para(
            "I server remoti sono il piano di esecuzione; SCARLET è il piano di controllo. Per ogni "
            "combinazione di applicazione e server esiste una riga, l'istanza applicativa, che tiene insieme "
            "le tre informazioni che contano.",
            "lead",
        ),
        P.table(
            [
                ["", "Campi", "Chi li scrive"],
                [
                    b("Stato desiderato"),
                    c("desired_version")
                    + ", "
                    + c("desired_state")
                    + " (RUNNING, STOPPED, ABSENT), "
                    + c("desired_replicas"),
                    "gli operatori, attraverso i deployment e le operazioni di ciclo di vita",
                ],
                [
                    b("Stato effettivo"),
                    c("actual_version")
                    + ", "
                    + c("actual_state")
                    + ", "
                    + c("actual_replicas")
                    + ", "
                    + c("actual_runtime")
                    + ", "
                    + c("health_status")
                    + ", "
                    + c("actual_observed_at"),
                    "il motore di deployment, le operazioni di ciclo di vita, il riconciliatore",
                ],
                [
                    b("Divergenza"),
                    c("drift_detected") + ", " + c("drift_type") + ", " + c("drift_details"),
                    "la funzione " + c("compute_drift(desiderato, effettivo)"),
                ],
            ],
            [16, 46, 38],
        ),
        P.space(6),
        P.h2("Stato desiderato, stato effettivo, divergenza"),
        P.para(
            "La divergenza non è un errore: è un'informazione. Dice che il mondo reale si è allontanato da "
            "ciò che era stato deciso, e il motivo può essere legittimo quanto un riavvio del server o grave "
            "quanto un container fermato a mano in produzione. SCARLET la classifica in cinque tipi, così che "
            "l'operatore sappia subito che cosa sta guardando."
        ),
        P.table(
            [
                ["Tipo", "Che cosa è successo", "Reazione tipica"],
                [
                    c("VERSION"),
                    "sull'host gira una versione diversa da quella desiderata",
                    "ridistribuire la versione attesa oppure accettare quella presente",
                ],
                [
                    c("STATE"),
                    "l'applicazione dovrebbe essere avviata ed è ferma, o viceversa",
                    "avviare o fermare dalla pagina dell'applicazione",
                ],
                [
                    c("UNEXPECTED_STOP"),
                    "il container è uscito senza che nessuno lo abbia chiesto",
                    "leggere i log: quasi sempre è l'applicazione a essere terminata",
                ],
                [
                    c("MISSING"),
                    "il container non esiste più sull'host",
                    "riavviare il rilascio; verificare linger e politiche di riavvio",
                ],
                [
                    c("RUNTIME"),
                    "l'applicazione gira con un runtime diverso da quello registrato",
                    "allineare la scheda dell'host o l'installazione",
                ],
            ],
            [16, 46, 38],
        ),
        P.space(5),
        P.callout(
            "Il riconciliatore "
            + b("osserva sempre")
            + " ma "
            + b("interviene solo se glielo si chiede")
            + ", e "
            "solo negli ambienti non di produzione. È una scelta deliberata: un sistema che corregge da solo la "
            "produzione nasconde gli incidenti invece di renderli visibili.",
            "info",
            title="Osservare non significa correggere",
        ),
    ]

    # ============================= 3
    s += P.section("3. Componenti e topologia", "c3")
    s += [
        P.para(
            "Il control plane è un insieme di processi che girano come container su una sola macchina. Gli "
            "unici due componenti che parlano con il mondo esterno sono nginx, verso gli operatori, e il "
            "worker, verso i server gestiti.",
            "lead",
        ),
        fig_componenti(),
        P.caption("Figura 2 — I processi del control plane e i due soli flussi verso l'esterno."),
        P.space(8),
        P.table(
            [
                ["Componente", "Ruolo", "Perché è separato"],
                [
                    "nginx",
                    "termina il TLS, reindirizza la 80 sulla 443, applica il limite di dimensione degli upload",
                    "l'applicazione non gestisce mai TLS né file di grandi dimensioni in ingresso",
                ],
                [
                    "gunicorn (web)",
                    "serve la console e l'API: autenticazione, autorizzazioni, validazione, audit",
                    "risponde in millisecondi; non esegue mai operazioni remote in linea",
                ],
                [
                    "worker Celery",
                    "esegue deployment, operazioni di ciclo di vita, discover, riconciliazione",
                    "un rilascio dura minuti: bloccare una richiesta HTTP per tutto quel tempo sarebbe fragile",
                ],
                [
                    "beat",
                    "pianifica riconciliazione, controlli di salute e pulizia",
                    "separa la pianificazione dall'esecuzione: il worker può essere riavviato senza perdere il calendario",
                ],
                [
                    "PostgreSQL",
                    "stato, piani, passi, audit, configurazioni",
                    "unica fonte di verità del control plane",
                ],
                [
                    "Redis",
                    "coda dei job e lock distribuiti",
                    "serve un meccanismo veloce e atomico per impedire due operazioni sulla stessa coppia applicazione-host",
                ],
                [
                    "Volume artefatti",
                    "i pacchetti di rilascio caricati",
                    "i file non stanno nel database: restano su disco con il loro checksum",
                ],
            ],
            [16, 42, 42],
        ),
    ]

    # ============================= 4
    s += P.section("4. I livelli del software", "c4")
    s += [
        P.para(
            "La regola è una sola e vale per tutto il codice: "
            + b("ogni livello parla solo con quello " "immediatamente sotto")
            + ". Una rotta non apre una connessione SSH, un servizio non costruisce un "
            "comando " + c("podman") + ", un adattatore non sa che esiste Flask.",
            "lead",
        ),
        fig_livelli(),
        P.caption(
            "Figura 3 — La pila dei livelli. Le frecce sono l'unica direzione di dipendenza ammessa."
        ),
        P.space(6),
        P.callout(
            "Il beneficio si vede quando qualcosa va storto. Se un rilascio fallisce su un host, la causa sta "
            "in un punto solo della pila e il passo che l'ha incontrata è già registrato con il comando "
            "eseguito, l'uscita e il codice di ritorno. Non occorre ricostruire che cosa è stato lanciato: è "
            "scritto.",
            "ok",
        ),
    ]

    # ============================= 5
    s += P.section("5. Gli oggetti di dominio", "c5")
    s += [
        P.para(
            "Sono definiti in "
            + c("app/deployment/domain.py")
            + " e non dipendono né dal database né dal "
            "framework web. È il vocabolario con cui il motore ragiona.",
            "lead",
        ),
        P.table(
            [
                ["Oggetto", "Che cosa rappresenta", "Contenuto"],
                [
                    c("DesiredApplicationState"),
                    "che cosa deve esserci sull'host",
                    "applicazione, versione, stato, repliche, immagine, manifest, variabili, porte, volumi, sonda di salute, namespace",
                ],
                [
                    c("ActualApplicationState"),
                    "che cosa è stato osservato",
                    "versione, stato, repliche, salute, dettagli grezzi del runtime",
                ],
                [
                    c("DriftReport"),
                    "la differenza fra i due",
                    "risultato di " + c("compute_drift") + ": tipo, dettaglio, presenza",
                ],
                [
                    c("PlanStep"),
                    "un passo previsto",
                    "identificativo, titolo, tipo, parametri, "
                    + c("critical")
                    + ", "
                    + c("rollback_trigger"),
                ],
                [
                    c("DeploymentPlan"),
                    "il piano completo",
                    "riferimento, applicazione, host, runtime, stato desiderato, versione precedente, passi, strategia, rollback automatico",
                ],
                [
                    c("StepExecution"),
                    "l'esito di un passo",
                    "stato, durata, comandi eseguiti, uscita, errore",
                ],
                [
                    c("DeploymentExecution"),
                    "l'esecuzione completa",
                    "la traccia che viene salvata in "
                    + c("Deployment")
                    + " e "
                    + c("DeploymentStep"),
                ],
            ],
            [22, 30, 48],
        ),
        P.space(6),
        P.para(
            "La separazione fra "
            + b("piano")
            + " ed "
            + b("esecuzione")
            + " è ciò che rende il sistema "
            "ispezionabile. Il piano viene calcolato e salvato come JSON prima di toccare l'host: è possibile "
            "leggerlo, confrontarlo con quello di un rilascio precedente e capire che cosa sarebbe successo, "
            "anche per un deployment che non è mai partito."
        ),
    ]

    # ============================= 6
    s += P.section("6. Anatomia di un rilascio", "c6")
    s += [
        P.h2("Dal wizard alla coda"),
        P.para(
            "L'operatore sceglie applicazione, versione e destinazioni. Prima ancora di mettere qualcosa in "
            "coda, il servizio verifica i permessi, applica la guardia di produzione, controlla la "
            "compatibilità fra manifest e host, cerca conflitti con operazioni in corso ed esegue i controlli "
            "preliminari che non richiedono l'host."
        ),
        P.code(
            [
                "DeploymentService.create()",
                "  risolve applicazione, versione e host; autorizza (prod.* sugli host PROD)",
                "  ProductionGuard.check_operation: frase digitata, motivazione, approvazione",
                "  regole di compatibilita, conflitti, pre-flight statico",
                "  crea DeploymentBatch e Deployment  (CREATED › QUEUED oppure PENDING_APPROVAL)",
                "  Celery: run_deployment_batch › deploy_application(id)",
                "",
                "DeploymentEngine.execute()",
                "  acquisisce il lock  runtime:{host}:{applicazione}",
                "  costruisce DesiredApplicationState da manifest + configurazione + segreti",
                "  DeploymentPlanner.plan() › DeploymentPlan, salvato come JSON",
                "  per ogni passo: transizione di stato, riga DeploymentStep, chiamata all'adattatore",
                "  in caso di errore: stato di fallimento, notifica, rollback automatico se previsto",
            ],
            title="Il percorso, dal clic all'host",
        ),
        P.space(6),
        P.h2("I tredici passi del piano"),
        P.para(
            "Il piano è sempre lo stesso nella struttura, e cambia nei dettagli a seconda del runtime, del "
            "manifest e del fatto che si tratti di un rilascio o di un ritorno alla versione precedente. I "
            "ganci del manifest, quando abilitati, si inseriscono fra i passi previsti."
        ),
        fig_pipeline(),
        P.caption(
            "Figura 4 — I passi del piano. Da activate in poi un errore innesca il rollback automatico."
        ),
        P.space(8),
        P.table(
            [
                ["#", "Passo", "Che cosa fa", "Critico"],
                ["1", c("validate"), "verifica il pacchetto e il suo checksum nell'archivio", "sì"],
                [
                    "2",
                    c("preflight"),
                    "controlli sull'host: SSH, runtime, disco, memoria, porte, percorso base",
                    "sì",
                ],
                ["3", c("prepare"), "crea il layout remoto: releases, shared, staging", "sì"],
                [
                    "4",
                    c("transfer"),
                    "invia il pacchetto via SFTP in " + c(".part") + ", poi rinomina",
                    "sì",
                ],
                [
                    "5",
                    c("verify"),
                    "confronta " + c("sha256sum") + " remoto con quello atteso",
                    "sì",
                ],
                [
                    "6",
                    c("extract"),
                    "estrae nella cartella della release, senza proprietari né permessi originali",
                    "sì",
                ],
                [
                    "7",
                    c("configure"),
                    "scrive "
                    + c("shared/config/scarlet.env")
                    + " unendo manifest, configurazione e segreti",
                    "sì",
                ],
                [
                    "—",
                    c("hook pre_deploy") + " / " + c("migrate"),
                    "script del pacchetto, solo se i ganci sono abilitati per l'applicazione",
                    "sì",
                ],
                [
                    "8",
                    c("install"),
                    "carica o scarica l'immagine e crea il container; su Kubernetes applica gli oggetti",
                    "sì",
                ],
                [
                    "9",
                    c("activate"),
                    "sposta il symlink " + c("current") + " sulla nuova release",
                    "sì, innesca il rollback",
                ],
                [
                    "10",
                    c("start"),
                    "avvia l'applicazione con le repliche richieste",
                    "sì, innesca il rollback",
                ],
                [
                    "11",
                    c("health"),
                    "esegue la sonda dall'host stesso, con tentativi e intervallo del manifest",
                    "sì, innesca il rollback",
                ],
                ["—", c("hook post_deploy"), "script finali del pacchetto", "no"],
                [
                    "12",
                    c("finalize"),
                    "aggiorna lo stato effettivo dell'istanza e chiude il deployment",
                    "sì",
                ],
                ["13", c("cleanup"), "ripulisce lo staging e le release eccedenti", "no"],
            ],
            [4, 16, 62, 18],
            font_size=8.4,
        ),
        P.space(6),
        P.h2("La macchina a stati"),
        P.para(
            "Ogni transizione è esplicita e viene scritta prima di essere eseguita. Gli stati di fallimento "
            "sono distinti per fase, non generici: dal solo stato finale si capisce dove si è fermato il "
            "rilascio."
        ),
        P.table(
            [
                ["Fase", "Stati di avanzamento", "Stato di fallimento"],
                [
                    "Creazione e approvazione",
                    c("CREATED")
                    + ", "
                    + c("PENDING_APPROVAL")
                    + ", "
                    + c("APPROVED")
                    + ", "
                    + c("QUEUED"),
                    c("REJECTED") + ", " + c("CANCELLED"),
                ],
                ["Validazione", c("VALIDATING") + ", " + c("VALIDATED"), c("VALIDATION_FAILED")],
                ["Controlli sull'host", c("PREFLIGHT"), c("PREFLIGHT_FAILED")],
                [
                    "Trasferimento",
                    c("TRANSFERRING") + ", " + c("TRANSFERRED"),
                    c("TRANSFER_FAILED"),
                ],
                ["Installazione", c("INSTALLING") + ", " + c("INSTALLED"), c("INSTALL_FAILED")],
                ["Avvio", c("STARTING") + ", " + c("STARTED"), c("START_FAILED")],
                ["Verifica di salute", c("HEALTH_CHECKING"), c("HEALTH_CHECK_FAILED")],
                [
                    "Esito",
                    c("SUCCESS"),
                    c("ROLLBACK_REQUIRED")
                    + ", "
                    + c("ROLLING_BACK")
                    + ", "
                    + c("ROLLED_BACK")
                    + ", "
                    + c("FAILED"),
                ],
            ],
            [22, 48, 30],
        ),
        P.space(5),
        P.callout(
            "I tentativi automatici esistono, ma solo per gli errori dichiarati ripetibili (connessione SSH "
            "caduta, timeout, trasferimento interrotto) e "
            + b("solo prima che lo stato remoto sia cambiato")
            + ". Nessun passo che abbia già modificato l'host viene ripetuto alla cieca.",
            "warn",
            title="Quando SCARLET riprova",
        ),
    ]

    # ============================= 7
    s += P.section("7. Attivazione atomica e rollback", "c7")
    s += [
        P.para(
            "Il momento più delicato di un rilascio è il passaggio dalla vecchia alla nuova versione. SCARLET "
            "lo riduce a una singola operazione del filesystem che il kernel garantisce indivisibile.",
            "lead",
        ),
        fig_attivazione(),
        P.caption(
            "Figura 5 — Lo scambio del symlink current: un solo rename, nessuno stato intermedio."
        ),
        P.space(8),
        P.para(
            "Il vantaggio pratico è che "
            + b("la versione precedente resta sull'host")
            + ", già estratta e "
            "pronta. Un rollback non ha bisogno di ritrasferire nulla: rifà gli stessi passi con la release "
            "precedente come destinazione, quindi è veloce e non dipende dalla rete né dalla disponibilità "
            "del pacchetto. Quante release conservare è un'impostazione di sistema; la corrente e la "
            "precedente non vengono mai eliminate."
        ),
        P.space(4),
        P.table(
            [
                ["Situazione", "Comportamento"],
                [
                    "errore prima di " + c("activate"),
                    "il deployment fallisce, l'host resta con la versione precedente attiva e in esecuzione; nessun rollback è necessario",
                ],
                [
                    "errore in " + c("activate") + ", " + c("start") + " o " + c("health"),
                    "se il rollback automatico è abilitato e una versione precedente esiste, parte subito: "
                    + c("ROLLBACK_REQUIRED")
                    + " › "
                    + c("ROLLING_BACK")
                    + " › "
                    + c("ROLLED_BACK"),
                ],
                [
                    "rollback richiesto da un operatore",
                    "è un deployment a tutti gli effetti, con il proprio riferimento "
                    + c("RBK-…")
                    + ", i propri passi e il proprio audit",
                ],
                [
                    "rollback su PROD",
                    "richiede il permesso "
                    + c("prod.deployment.rollback")
                    + " e può essere disabilitato globalmente da un'impostazione",
                ],
            ],
            [26, 74],
        ),
    ]

    # ============================= 8
    s += P.section("8. Adattatori di runtime", "c8")
    s += [
        P.para(
            "Il motore non sa che cosa sia un container. Parla con un'interfaccia di quindici operazioni e "
            "riceve l'implementazione giusta da una fabbrica, in base al runtime registrato sull'host.",
            "lead",
        ),
        P.code(
            [
                "detect · status · version · inspect · logs · health · install · start",
                "stop · restart · remove · rollback · scale · apply",
                "",
                "RuntimeFactory.get(runtime_type) › DockerRuntimeAdapter | PodmanRuntimeAdapter | KubernetesRuntimeAdapter",
            ],
            title="L'interfaccia RuntimeAdapter",
        ),
        P.space(6),
        P.table(
            [
                ["", "Podman", "Docker", "Kubernetes"],
                [
                    "Modalità consigliata",
                    "rootless, senza alcun privilegio",
                    "demone di sistema, utente nel gruppo docker",
                    "API del cluster con kubeconfig (senza SSH), oppure kubectl via SSH",
                ],
                [
                    "Volumi",
                    "montati con " + c(":Z") + " per SELinux",
                    "montati senza rietichettatura",
                    "PersistentVolumeClaim e ConfigMap",
                ],
                [
                    "Immagini senza rete",
                    c("podman load -i") + " dall'archivio nel pacchetto",
                    c("docker load -i"),
                    "richiede un registry raggiungibile dal cluster",
                ],
                [
                    "Unità di esecuzione",
                    "container con etichette " + c("scarlet.*"),
                    "container con etichette " + c("scarlet.*"),
                    "Deployment, Service, ConfigMap nel namespace",
                ],
                [
                    "Salute",
                    "sonda HTTP o TCP dall'host su " + c("127.0.0.1"),
                    "identica a Podman",
                    "stato del Deployment e dei pod",
                ],
                [
                    "Riavvio dopo il reboot",
                    "linger più politica di riavvio, oppure unità systemd",
                    "gestito dal demone",
                    "gestito dal cluster",
                ],
            ],
            [18, 28, 26, 28],
        ),
        P.space(5),
        P.para(
            "Aggiungere un runtime significa scrivere una classe che implementa l'interfaccia e registrarla "
            "nella fabbrica. Nessun altro file cambia: né il pianificatore, né la macchina a stati, né le "
            "rotte, né l'interfaccia utente."
        ),
        P.space(4),
        P.h2("Il caso particolare: un target senza shell"),
        P.para(
            "Un cluster Kubernetes registrato con un kubeconfig non è una macchina in cui SCARLET possa "
            "entrare. Non esiste una sessione SSH, non esiste una directory di rilascio, non c'è una chiave "
            "host da approvare. È l'unico target che rompe l'assunto implicito di tutto il resto del "
            "sistema, e per questo l'accesso passa da un punto solo."
        ),
        P.table(
            [
                ["Elemento", "Come si comporta su un target cluster"],
                [
                    c("open_target(host)"),
                    "unico ingresso: restituisce una sessione SSH oppure, per un cluster, un esecutore che "
                    "rifiuta ogni comando. Un percorso di codice che presupponga ancora una shell fallisce "
                    "in modo esplicito invece di funzionare a metà",
                ],
                [
                    "Piano di deployment",
                    "senza "
                    + c("prepare")
                    + ", "
                    + c("transfer")
                    + ", "
                    + c("verify")
                    + ", "
                    + c("extract")
                    + ", "
                    + c("activate")
                    + ", "
                    + c("cleanup")
                    + " e senza ganci: resta "
                    + c("validate › preflight › configure › install › start › health › finalize"),
                ],
                [
                    "Controlli preliminari",
                    "al posto di disco, memoria e porte: API raggiungibile, namespace, permessi della "
                    "credenziale verificati con una access review, oggetti presenti nel pacchetto",
                ],
                [
                    "Configurazione",
                    "non c'è un file da scrivere su un host: diventa un Secret nel namespace, collegato al "
                    "container con " + c("envFrom"),
                ],
                [
                    "Diagnosi di un errore",
                    "l'errore di un rollout porta con sé gli eventi del cluster e lo stato dei pod, che "
                    "sono ciò che distingue un'immagine non scaricabile da una sonda che non passa",
                ],
            ],
            [24, 76],
        ),
        P.space(5),
        P.para(
            "Anche il cluster è dietro una porta, non dietro la libreria ufficiale: l'adattatore parla con "
            "un'interfaccia ristretta, implementata sul client reale in esercizio e da un cluster in "
            "memoria nei test. È lo stesso schema del livello SSH con il suo client falso, e permette di "
            "verificare rilasci, divergenza, rollback e rimozione senza alcun cluster."
        ),
    ]

    # ============================= 9
    s += P.section("9. Il contratto del pacchetto", "c9")
    s += [
        P.para(
            "Fra chi sviluppa le applicazioni e chi le mette in esercizio c'è un contratto scritto e "
            "versionato. Un team che lo rispetta produce rilasci che SCARLET sa validare, distribuire, "
            "sorvegliare e riportare indietro, senza sapere nulla del funzionamento interno di SCARLET.",
            "lead",
        ),
        P.code(
            [
                "customer-api-2.5.0.scarlet.tar.gz",
                "  manifest.yaml            obbligatorio, manifest_version: 1",
                "  application/             immagine salvata, binari, file statici",
                "  config/                  file di ambiente non segreti",
                "  scripts/                 ganci *.sh richiamati dal manifest",
                "  kubernetes/              manifest YAML, per il runtime kubernetes",
                "  checksums.sha256         generato dal packager",
            ],
            title="Struttura dell'archivio",
        ),
        P.space(6),
        P.table(
            [
                ["Sezione del manifest", "A che cosa serve"],
                [
                    c("application") + ", " + c("version") + ", " + c("runtime"),
                    "identità del rilascio; il codice deve coincidere con l'applicazione registrata in SCARLET e la versione è immutabile",
                ],
                [
                    c("image"),
                    "nome, tag, eventuale archivio dentro il pacchetto e politica di scaricamento ("
                    + c("if-not-present")
                    + ", "
                    + c("always")
                    + ", "
                    + c("never")
                    + ")",
                ],
                [
                    c("ports") + ", " + c("volumes"),
                    "porte pubblicate e volumi persistenti, mappati sull'area "
                    + c("shared")
                    + " che sopravvive ai rilasci",
                ],
                [
                    c("environment") + ", " + c("environment_files") + ", " + c("secrets"),
                    "variabili non segrete nel pacchetto; i nomi dei segreti sono dichiarati qui e "
                    + b("devono")
                    + " essere valorizzati in SCARLET prima del rilascio",
                ],
                [
                    c("healthcheck"),
                    "tipo ("
                    + c("http")
                    + ", "
                    + c("https")
                    + ", "
                    + c("tcp")
                    + ", "
                    + c("command")
                    + ", "
                    + c("container_status")
                    + ", "
                    + c("kubernetes_status")
                    + "), percorso, porta, tentativi, intervallo",
                ],
                [
                    c("deployment") + ", " + c("resources"),
                    "strategia, timeout, politica di riavvio, utente del container, limiti di CPU e memoria",
                ],
                [
                    c("hooks"),
                    "script eseguiti sull'host, solo se le operations li hanno abilitati per quell'applicazione",
                ],
                [
                    c("kubernetes") + ", " + c("compose"),
                    "modalità alternative all'immagine singola",
                ],
            ],
            [26, 74],
        ),
        P.space(6),
        P.callout(
            "Il validatore ispeziona l'archivio "
            + b("membro per membro, senza estrarlo")
            + ": rifiuta link "
            "simbolici e fisici, dispositivi, bit setuid, percorsi assoluti e risalite di directory, e applica "
            "limiti al numero di file e alla dimensione decompressa. Un pacchetto malevolo viene respinto "
            "prima di toccare il disco, e nessuno script del pacchetto viene mai eseguito sul server SCARLET.",
            "danger",
            title="Il pacchetto è dato, non codice",
        ),
    ]

    # ============================= 10
    s += P.section("10. Sicurezza per progetto", "c10")
    s += [
        P.para(
            "SCARLET esegue operazioni privilegiate su server di produzione: la postura predefinita è "
            "restrittiva e i controlli sono nel codice, non nell'interfaccia.",
            "lead",
        ),
        P.h2("Come nasce un comando remoto"),
        fig_comando(),
        P.caption("Figura 6 — Il percorso di ogni comando, dalla costruzione all'esecuzione."),
        P.space(8),
        P.table(
            [
                ["Minaccia", "Controllo"],
                [
                    "credenziali SSH sottratte dal database o da un backup",
                    "cifratura Fernet con chiave esterna al database; mai esposte da API, interfaccia, log o audit; rotazione per aggiunta",
                ],
                [
                    "intercettazione sulla connessione SSH",
                    "verifica rigida della chiave host; le chiavi sconosciute vanno approvate da un amministratore; una difformità blocca l'host e genera un evento CRITICAL",
                ],
                [
                    "iniezione di comandi attraverso nomi, versioni, manifest, filtri",
                    "comandi come lista di argomenti, "
                    + c("shlex.quote")
                    + " su ognuno, allow-list degli eseguibili, espressioni regolari su ogni valore che finisce in un comando",
                ],
                [
                    "pacchetto di rilascio malevolo",
                    "ispezione membro per membro senza estrazione, rifiuto di link e file speciali, limiti di numero e dimensione, schema del manifest rigido",
                ],
                [
                    "modifica non autorizzata in produzione",
                    "permessi "
                    + c("prod.*")
                    + ", motivazione obbligatoria, frase da digitare, approvazione di una seconda persona, lock per applicazione e host",
                ],
                [
                    "scalata di privilegi dall'interfaccia",
                    "RBAC applicato in ogni rotta e in ogni servizio; nascondere un pulsante è solo cosmesi",
                ],
                [
                    "attacchi web (XSS, CSRF, clickjacking)",
                    "autoescape, CSP senza script in linea, token CSRF, "
                    + c("frame-ancestors 'none'")
                    + ", cookie Secure, HttpOnly e SameSite",
                ],
                [
                    "forza bruta sulle credenziali",
                    "limite di frequenza sul login, blocco dell'account, Argon2id, messaggi di errore identici",
                ],
                [
                    "esecuzione arbitraria da parte degli operatori",
                    "non esiste una funzione per eseguire comandi liberi; la shell diagnostica è disabilitata e rifiutata in configurazione di produzione",
                ],
            ],
            [24, 76],
        ),
        P.space(6),
        P.h2("Controlli sulla produzione"),
        P.para(
            "Un host marcato come produzione cambia le regole per ogni operazione che lo riguarda. Il permesso "
            "di base non basta: serve anche la sua variante "
            + c("prod.*")
            + ". A questo si aggiungono i "
            "controlli configurabili a livello di sistema, e vale sempre il più restrittivo fra impostazione "
            "globale e regola dell'ambiente."
        ),
        P.table(
            [
                ["Controllo", "Effetto"],
                [
                    "Permesso " + c("prod.<permesso>"),
                    "OPERATOR può agire solo su DEV; PROD_OPERATOR e ADMIN anche su PROD",
                ],
                [
                    "Frase digitata",
                    "l'operatore deve scrivere una frase esatta, configurabile, per confermare l'operazione",
                ],
                [
                    "Motivazione obbligatoria",
                    "il testo finisce nell'audit e nella notifica, accanto al nome di chi ha agito",
                ],
                [
                    "Approvazione di una seconda persona",
                    "il deployment resta in "
                    + c("PENDING_APPROVAL")
                    + "; chi lo ha richiesto non può approvarlo",
                ],
                [
                    "Lock per applicazione e host",
                    "impedisce due operazioni contemporanee sulla stessa coppia, anche da sessioni diverse",
                ],
            ],
            [28, 72],
        ),
    ]

    # ============================= 11
    s += P.section("11. Riconciliazione e divergenza", "c11")
    s += [
        P.para(
            "Il riconciliatore è il motivo per cui SCARLET sa dirvi che cosa sta girando davvero sui server, "
            "e non soltanto che cosa è stato distribuito l'ultima volta.",
            "lead",
        ),
        fig_riconciliazione(),
        P.caption("Figura 7 — Il ciclo di riconciliazione: osserva, confronta, segnala."),
        P.space(8),
        P.table(
            [
                ["Aspetto", "Comportamento predefinito"],
                ["Frequenza", "ogni 5 minuti, modificabile da " + c("Sistema › Impostazioni")],
                ["Ambito", "tutti gli host abilitati; gli host disabilitati sono esclusi"],
                [
                    "Effetto normale",
                    "aggiorna lo stato effettivo e la divergenza, senza toccare l'host",
                ],
                [
                    "Rimedio automatico",
                    "disattivato; abilitabile e comunque limitato agli ambienti non di produzione",
                ],
                [
                    "Visibilità",
                    "riquadro delle divergenze sul cruscotto, scheda dell'applicazione, notifiche",
                ],
            ],
            [24, 76],
        ),
        P.space(5),
        P.para(
            "Accanto alla riconciliazione lavora il controllo di salute periodico, che interroga la sonda "
            "dichiarata nel manifest e conserva lo storico degli esiti. Le due informazioni sono distinte: "
            "un'applicazione può essere in esecuzione nella versione giusta e comunque rispondere male alla "
            "sonda."
        ),
    ]

    # ============================= 12
    s += P.section("12. Job asincroni, code e lock", "c12")
    s += [
        P.para(
            "Tutto ciò che tocca un host remoto passa da un job. La richiesta HTTP si limita a validare, "
            "autorizzare, creare le righe e mettere in coda: restituisce un identificativo e termina.",
            "lead",
        ),
        P.table(
            [
                ["Coda", "Che cosa contiene"],
                [
                    c("scarlet"),
                    "operazioni di ciclo di vita e operazioni sugli host: avvio, arresto, riavvio, stato, log, test di connessione, discover",
                ],
                [
                    c("scarlet-deploy"),
                    "deployment e rollback: sono i job lunghi, tenuti separati per non fare da tappo alle operazioni brevi",
                ],
                [
                    c("scarlet-maintenance"),
                    "riconciliazione, controlli di salute, pulizia dei dati e delle release remote",
                ],
            ],
            [22, 78],
        ),
        P.space(6),
        P.table(
            [
                ["Meccanismo", "Come funziona"],
                [
                    "Lock distribuito",
                    "chiave "
                    + c("runtime:{host}:{applicazione}")
                    + " in Redis con "
                    + c("SET NX PX")
                    + " e rilascio via script Lua; ripiego sul database se Redis non è disponibile",
                ],
                [
                    "Tentativi",
                    "attesa esponenziale, solo per errori dichiarati ripetibili e solo prima che lo stato remoto sia cambiato",
                ],
                [
                    "Timeout",
                    "ogni comando remoto ne ha uno; il trasferimento dei file ne ha uno proprio, più generoso",
                ],
                [
                    "Idempotenza",
                    "i passi che hanno già prodotto il risultato atteso vengono saltati, ad esempio la release già presente durante un rollback",
                ],
            ],
            [22, 78],
        ),
    ]

    # ============================= 13
    s += P.section("13. Modello dei dati", "c13")
    s += [
        P.para(
            "Il database è la sola fonte di verità del control plane. Le tabelle sono raggruppate per "
            "responsabilità; le migrazioni sono versionate e applicate all'avvio.",
            "lead",
        ),
        P.table(
            [
                ["Gruppo", "Tabelle", "Note"],
                [
                    "Utenti e permessi",
                    c("users, roles, permissions, role_permissions, user_roles, api_tokens"),
                    "password con Argon2id, token con impronta SHA-256",
                ],
                [
                    "Infrastruttura",
                    c(
                        "environments, target_hosts, target_credentials, ssh_keys, host_groups, host_group_members, runtime_capabilities"
                    ),
                    "le credenziali sono cifrate a riposo",
                ],
                [
                    "Applicazioni",
                    c("applications, application_versions, packages, application_instances"),
                    "le versioni sono immutabili; le istanze tengono desiderato ed effettivo",
                ],
                [
                    "Operazioni",
                    c(
                        "deployment_batches, deployments, deployment_steps, deployment_approvals, lifecycle_operations, operation_logs, health_checks, distributed_locks"
                    ),
                    "il piano è salvato come JSON sul deployment",
                ],
                [
                    "Governo",
                    c(
                        "audit_logs, security_events, configurations, configuration_entries, configuration_versions, notifications, system_settings"
                    ),
                    "l'audit è in sola aggiunta",
                ],
            ],
            [16, 54, 30],
            font_size=8.3,
        ),
        P.space(5),
        P.para(
            "Gli indici seguono le interrogazioni reali: deployment per host, per applicazione, per data e per "
            "stato; audit per data, utente e azione; operazioni per stato e data; versioni per applicazione; "
            "istanze per host e applicazione."
        ),
    ]

    # ============================= 14
    s += P.section("14. Osservabilità e tracciabilità", "c14")
    s += [
        P.table(
            [
                ["Strumento", "A che cosa serve"],
                [
                    "Identificativo di richiesta (ULID)",
                    "generato a ogni richiesta, restituito nell'intestazione "
                    + c("X-Request-ID")
                    + ", riportato nei log JSON, nelle righe di audit e nel contesto del worker: lega il clic dell'operatore al comando eseguito sull'host",
                ],
                [
                    "Riferimenti leggibili",
                    c("DEP-AAAAMMGG-nnnnnn")
                    + " per i deployment, "
                    + c("RBK-…")
                    + " per i rollback, "
                    + c("OP-…")
                    + " per le operazioni, "
                    + c("BATCH-…")
                    + " per i lotti",
                ],
                [
                    "Audit in sola aggiunta",
                    "chi, che cosa, su quale oggetto, con quale esito e con quale motivazione; non modificabile dall'applicazione",
                ],
                [
                    "Eventi di sicurezza",
                    "login falliti, blocchi, difformità di chiave host, operazioni negate, con livello di gravità",
                ],
                [
                    "Log dei passi",
                    "per ogni passo: comando, uscita standard, errori, codice di uscita e durata, ripuliti dai segreti prima del salvataggio",
                ],
                [
                    "Endpoint di servizio",
                    c("/api/health")
                    + " (vitalità), "
                    + c("/api/ready")
                    + " (database, Redis, worker), "
                    + c("/api/metrics")
                    + " (Prometheus)",
                ],
            ],
            [24, 76],
        ),
        P.space(6),
        P.callout(
            "La conseguenza pratica: davanti a un incidente si parte dal riferimento del deployment e si "
            "arriva, senza salti, al comando esatto eseguito sull'host, all'ora precisa, per conto di quale "
            "utente e con quale motivazione dichiarata.",
            "ok",
        ),
    ]

    # ============================= 15
    s += P.section("15. Punti di estensione", "c15")
    s += [
        P.para(
            "L'architettura è stata pensata per essere allargata nei punti in cui è prevedibile che serva, "
            "senza rimettere mano al motore.",
            "lead",
        ),
        P.table(
            [
                ["Estensione", "Come si realizza"],
                [
                    "Nuovo runtime",
                    "implementare "
                    + c("RuntimeAdapter")
                    + " e registrarlo in "
                    + c("RuntimeFactory"),
                ],
                [
                    "Archivio artefatti diverso",
                    "implementare " + c("ArtifactStorage") + " (ad esempio S3 o MinIO)",
                ],
                [
                    "Segreti da un vault esterno",
                    "implementare "
                    + c("SecretProvider")
                    + " (Vault, AWS Secrets Manager, Secret di Kubernetes)",
                ],
                [
                    "Nuovo ambiente oltre DEV e PROD",
                    "inserire una riga in "
                    + c("environments")
                    + ": il modello non è limitato a due",
                ],
                [
                    "Approvazioni a più firme",
                    "le righe "
                    + c("DeploymentApproval")
                    + " e lo stato "
                    + c("PENDING_APPROVAL")
                    + " esistono già; si estende "
                    + c("ProductionGuard.check_approval"),
                ],
                [
                    "Strategie di rilascio",
                    c("DeploymentStrategy.CANARY")
                    + " è riservata; il lotto gestisce già sequenziale e parallelo",
                ],
                [
                    "Aggiornamenti in tempo reale",
                    "oggi l'interfaccia interroga periodicamente gli endpoint dei passi; i passi sono salvati a ogni cambiamento, quindi un canale WebSocket o SSE si aggiunge senza toccare il motore",
                ],
            ],
            [26, 74],
        ),
        P.space(8),
        P.para(
            "Questo documento è generato dal repository con "
            + c("python scripts/build_pdf_docs.py")
            + " e "
            "segue "
            + c("docs/architecture.md")
            + ", "
            + c("docs/security.md")
            + " e il codice del motore di "
            "deployment.",
            "small",
        ),
    ]
    return s


META = P.DocMeta(
    title="Architettura\ne funzionamento",
    subtitle="Come è fatto SCARLET e perché funziona così",
    kicker="Documento di architettura",
    version=VERSION,
    date=date.today().strftime("%d/%m/%Y"),
    audience="Architetti, sviluppatori, responsabili tecnici, sicurezza",
    summary=(
        "SCARLET non è un esecutore di script di deploy: è un control plane che tiene, per ogni applicazione "
        "e per ogni server, lo stato desiderato e quello osservato, e riduce la distanza fra i due. "
        "Questo documento descrive i livelli del software, gli oggetti di dominio, l'anatomia completa di un "
        "rilascio, l'attivazione atomica con rollback, gli adattatori di runtime, il contratto del pacchetto "
        "e i controlli di sicurezza, con i diagrammi che li mettono in relazione."
    ),
    filename="SCARLET-Architettura-e-Funzionamento.pdf",
    highlights=(
        "Il modello a stato desiderato e stato effettivo, e come nasce la divergenza",
        "I sei livelli del software e la sola direzione di dipendenza ammessa",
        "I tredici passi di un rilascio, il punto di non ritorno e il rollback automatico",
        "L'attivazione atomica della release e perché il ritorno indietro è immediato",
        "I controlli di sicurezza: comandi in allow-list, chiavi host, permessi di produzione",
        "Sette diagrammi che mettono in relazione componenti, passi e stati",
    ),
)


def main() -> Path:
    return P.build(META, story())


if __name__ == "__main__":
    print(main())
