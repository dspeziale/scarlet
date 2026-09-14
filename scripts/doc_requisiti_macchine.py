#!/usr/bin/env python3
"""Manuale PDF: cosa installare sulle macchine usate per il deploy.

Il contenuto è allineato a docs/installation.md, docs/ssh.md, docs/runtime-*.md e alla
allow-list dei binari in app/ssh/command.py. Costruire con scripts/build_pdf_docs.py.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdflib as P  # noqa: E402
from pdflib import b, c  # noqa: E402

VERSION = "SCARLET 1.0.0"


# --- figure ---------------------------------------------------------------------------------


def fig_topologia() -> P.Diagram:
    """Chi parla con chi, e che cosa vive su ogni macchina."""
    d = P.Diagram(174, 98)

    d.group(0, 72, 174, 26, "1 · POSTAZIONI")
    d.box(6, 74, 46, 15, "PC operatori", ["solo un browser", "nessuna installazione"], fill=P.PANEL)
    d.box(
        64,
        74,
        46,
        15,
        "PC / pipeline del team",
        ["build immagine", "e confezionamento"],
        fill=P.PANEL,
    )
    d.box(122, 74, 46, 15, "Monitoraggio (opz.)", ["Prometheus, probe"], fill=P.PANEL, dashed=True)

    d.group(0, 38, 174, 26, "2 · CONTROL PLANE — una sola macchina")
    d.box(
        6,
        40,
        162,
        18,
        "Server SCARLET",
        [
            "container: nginx · gunicorn (web) · worker Celery · beat · PostgreSQL 16 · Redis 7",
            "Oracle Linux 8.8+/9 · podman + podman-compose (oppure Docker Engine + compose)",
        ],
        stroke=P.RED,
        fill=P.colors.HexColor("#fdf3f4"),
    )

    d.group(0, 0, 174, 30, "3 · SERVER DI DESTINAZIONE — nessun agente SCARLET installato")
    d.box(6, 3, 50, 17, "Host DEV", ["podman + utilità", "utente scarlet"], fill=P.PANEL)
    d.box(62, 3, 50, 17, "Host PROD", ["podman + utilità", "utente scarlet"], fill=P.PANEL)
    d.box(
        118,
        3,
        50,
        17,
        "Host Kubernetes",
        ["kubectl oppure", "kubeconfig"],
        fill=P.PANEL,
        dashed=True,
    )

    d.arrow((29, 74), (29, 64), "HTTPS 443", color=P.RED, label_dy=0.6)
    d.arrow((87, 74), (87, 64), "API + token", color=P.RED, label_dy=0.6)
    d.arrow((145, 74), (145, 64), "443", color=P.MUTED, dashed=True, label_dy=0.6)
    d.arrow((31, 40), (31, 30), "SSH 22", color=P.RED, label_dy=0.6)
    d.arrow((87, 40), (87, 30), "SSH 22", color=P.RED, label_dy=0.6)
    d.arrow((143, 40), (143, 30), "22 oppure 6443", color=P.MUTED, dashed=True, label_dy=0.6)
    return d


def fig_layout_remoto() -> P.Diagram:
    """L'albero delle directory che SCARLET crea sul server di destinazione."""
    d = P.Diagram(174, 62)
    d.box(
        4,
        46,
        62,
        12,
        "/opt/scarlet",
        ["SCARLET_REMOTE_BASE_PATH", "di proprietà dell'utente SSH"],
        stroke=P.RED,
    )
    d.box(4, 28, 62, 12, "applications/<app>/", ["una cartella per applicazione"], fill=P.PANEL)
    d.arrow((35, 46), (35, 40))

    d.box(
        76,
        44,
        44,
        13,
        "releases/<versione>/",
        ["release estratta,", "immutabile"],
        fill=P.colors.white,
    )
    d.box(
        76,
        28,
        44,
        12,
        "current",
        ["symlink alla release attiva"],
        stroke=P.RED,
        fill=P.colors.HexColor("#fdf3f4"),
    )
    d.box(
        76, 13, 44, 12, "shared/", ["config · data · logs", "sopravvive ai rilasci"], fill=P.PANEL
    )
    d.box(76, 0, 44, 10, "staging/ · backups/", ["upload e lavoro temporaneo"], fill=P.PANEL)
    for y in (50, 34, 19, 5):
        d.arrow((66, 34), (76, y), "", color=P.MUTED)

    d.box(
        132,
        30,
        40,
        20,
        "Runtime",
        ["podman / docker /", "kubectl esegue", "il container"],
        fill=P.PANEL,
    )
    d.arrow((120, 34), (132, 38), "", color=P.MUTED)
    d.label(132, 24, "L'applicazione legge la sua configurazione da", size=7, color=P.MUTED)
    d.label(132, 20.5, "shared/config/scarlet.env", size=7, color=P.RED, bold=True)
    return d


def fig_flussi() -> P.Diagram:
    """I flussi di rete da autorizzare, con la direzione di apertura."""
    d = P.Diagram(174, 58)
    d.box(4, 38, 42, 14, "Browser operatori", [], fill=P.PANEL)
    d.box(66, 38, 46, 14, "Server SCARLET", [], stroke=P.RED)
    d.box(128, 38, 42, 14, "Registry immagini", [], fill=P.PANEL, dashed=True)
    d.box(66, 4, 46, 14, "Server di destinazione", [], fill=P.PANEL)
    d.box(4, 4, 42, 14, "Utenti applicazione", [], fill=P.PANEL)
    d.box(128, 4, 42, 14, "SMTP / K8s API", [], fill=P.PANEL, dashed=True)

    d.arrow((46, 45), (66, 45), "443/tcp", color=P.RED)
    d.arrow((89, 38), (89, 18), "22/tcp  obbligatoria", color=P.RED, label_dy=1.2)
    d.arrow((112, 11), (128, 11), "443", color=P.MUTED, dashed=True)
    d.arrow((66, 11), (46, 11), "porte app", color=P.MUTED)
    d.arrow((112, 45), (128, 45), "443", color=P.MUTED, dashed=True)
    d.arrow((100, 38), (128, 18), "587 / 6443", color=P.MUTED, dashed=True, label_dy=-3.4)
    d.label(
        87,
        30,
        "una sola porta verso gli host gestiti",
        size=7.2,
        color=P.RED,
        anchor="middle",
        bold=True,
    )
    return d


# --- contenuto -------------------------------------------------------------------------------


def story() -> list:
    s: list = []

    # ============================= 1
    s += P.toc(
        [
            (1, "1. A chi serve questo documento", "c1"),
            (2, "Le quattro famiglie di macchine", "c1"),
            (1, "2. Server di destinazione: requisiti", "c2"),
            (2, "Dimensionamento e sistema operativo", "c2"),
            (2, "Pacchetti da installare", "c2"),
            (2, "Comandi che SCARLET esegue davvero", "c2"),
            (1, "3. Server di destinazione: installazione", "c3"),
            (2, "Script completo, dalla macchina vuota", "c3"),
            (2, "Utente dedicato e Podman rootless", "c3"),
            (2, "Chiave SSH e authorized_keys", "c3"),
            (2, "SELinux e firewall locale", "c3"),
            (1, "4. Verifica prima di consegnare l'host", "c4"),
            (1, "5. Varianti: Docker e Kubernetes", "c5"),
            (1, "6. Il server SCARLET (control plane)", "c6"),
            (1, "7. Postazioni e macchine di build", "c7"),
            (1, "8. Matrice dei flussi di rete", "c8"),
            (1, "9. Errori tipici e come risolverli", "c9"),
            (1, "10. Checklist di consegna", "c10"),
            (1, "Appendice A. Elenco completo dei binari richiesti", "ca"),
            (1, "Appendice B. Documenti di riferimento", "cb"),
        ]
    )

    # ============================= capitolo 1
    s += P.section("1. A chi serve questo documento", "c1", first=False)
    s += [
        P.para(
            "Questo manuale elenca, macchina per macchina, il software da installare prima che SCARLET "
            "possa distribuire applicazioni. È pensato per chi prepara i server: sistemisti, team "
            "infrastruttura, chi apre le regole sui firewall. Ogni comando è verificato su Oracle Linux 9.",
            "lead",
        ),
        P.callout(
            "SCARLET è "
            + b("senza agente")
            + ". Sui server gestiti non si installa alcun componente SCARLET: "
            "nessun demone, nessuna libreria Python, nessun pacchetto proprietario. Servono soltanto un accesso "
            "SSH con un utente dedicato, un runtime di container e una manciata di utilità di sistema già "
            "presenti in qualsiasi installazione minima.",
            "ok",
            title="Il punto di partenza",
        ),
        P.space(4),
        P.h2("Le quattro famiglie di macchine"),
        P.para(
            "Prima di scendere nel dettaglio conviene avere chiaro il perimetro. Le macchine coinvolte sono "
            "quattro e hanno requisiti molto diversi: solo la seconda riga richiede un intervento su ogni "
            "server, le altre si preparano una volta sola."
        ),
        P.table(
            [
                ["Macchina", "Da installare", "Quante", "Capitolo"],
                [
                    b("Server di destinazione")
                    + "<br/>"
                    + "gli Oracle Linux su cui girano le applicazioni",
                    "runtime di container + utilità di sistema + utente dedicato con chiave SSH",
                    "una per ogni server gestito",
                    "2, 3, 4",
                ],
                [
                    b("Server SCARLET") + "<br/>" + "il control plane",
                    "podman e podman-compose (o Docker Engine), certificato TLS, il file .env",
                    "una sola, centrale",
                    "6",
                ],
                [
                    b("PC degli operatori"),
                    "nulla: un browser aggiornato",
                    "quante servono",
                    "7",
                ],
                [
                    b("PC o pipeline del team applicativo"),
                    "il proprio strumento di build più lo script che confeziona il pacchetto",
                    "una per team",
                    "7",
                ],
            ],
            [26, 38, 20, 12],
        ),
        P.space(8),
        fig_topologia(),
        P.caption("Figura 1 — Chi installa che cosa, e in quale direzione viaggia il traffico."),
        P.space(6),
        P.callout(
            "Le frecce hanno una sola direzione per un motivo preciso: i server di destinazione non devono mai "
            "poter raggiungere SCARLET. Non esistono callback, code in uscita o agenti che chiamano casa. Se un "
            "host viene compromesso, non ha alcun canale verso il control plane.",
            "info",
            title="Perché conta la direzione",
        ),
    ]

    # ============================= capitolo 2
    s += P.section("2. Server di destinazione: requisiti", "c2")
    s += [
        P.para(
            "Questo è il capitolo che riguarda "
            + b("le macchine usate per il deploy")
            + ". Tutto ciò che segue "
            "vale per ciascun server, sia in DEV sia in PROD: la configurazione è identica, cambiano solo le "
            "regole di autorizzazione applicate lato SCARLET.",
            "lead",
        ),
        P.h2("Dimensionamento e sistema operativo"),
        P.table(
            [
                ["Voce", "Minimo", "Consigliato", "Note"],
                [
                    "Sistema operativo",
                    "Oracle Linux 8.8",
                    "Oracle Linux 9.x",
                    "vanno bene RHEL, Rocky e AlmaLinux della stessa famiglia",
                ],
                [
                    "Architettura",
                    "x86_64",
                    "x86_64",
                    "l'immagine del container deve corrispondere all'architettura dell'host",
                ],
                [
                    "CPU",
                    "1 vCPU oltre a quelle dell'applicazione",
                    "2 vCPU",
                    "SCARLET non consuma CPU sull'host se non durante il rilascio",
                ],
                [
                    "RAM",
                    "512 MB liberi oltre all'applicazione",
                    "1 GB",
                    "il pre-flight confronta la memoria libera con quella dichiarata nel manifest",
                ],
                [
                    "Disco su " + c("/opt/scarlet"),
                    "5 GB",
                    "20 GB o più",
                    "vedi la formula qui sotto: pesa il numero di release conservate",
                ],
                [
                    "SELinux",
                    "enforcing",
                    "enforcing",
                    "non va disattivato: i volumi sono etichettati con " + c(":Z"),
                ],
                [
                    "Orologio",
                    "sincronizzato (chrony)",
                    "sincronizzato",
                    "gli scarti di orario rendono illeggibili audit e log correlati",
                ],
            ],
            [16, 20, 18, 46],
        ),
        P.space(6),
        P.para(
            "Lo spazio necessario si calcola così: "
            + b("dimensione del pacchetto × release da conservare")
            + " più lo spazio delle immagini nello storage del runtime. Il numero di release conservate è "
            "un'impostazione di SCARLET ("
            + c("Sistema › Impostazioni")
            + ", valore predefinito 5, la corrente e "
            "la precedente sono sempre mantenute). Le immagini non vengono eliminate automaticamente: se lo "
            "spazio è limitato, pianificare un " + c("podman image prune") + " periodico sull'host."
        ),
        P.h2("Pacchetti da installare"),
        P.para(
            "Un solo comando copre il caso normale, cioè un host con Podman. I pacchetti sono tutti nei "
            "repository standard di Oracle Linux: non serve alcun repository aggiuntivo."
        ),
        P.code(
            [
                "# Oracle Linux 9 — runtime consigliato (Podman rootless)",
                "sudo dnf install -y podman podman-plugins fuse-overlayfs slirp4netns \\",
                "                    tar gzip coreutils curl nmap-ncat",
                "",
                "# openssh-server è già presente e attivo in ogni installazione standard",
                "sudo systemctl enable --now sshd",
            ],
            title="Installazione dei pacchetti",
        ),
        P.space(6),
        P.table(
            [
                ["Pacchetto", "Perché serve", "Obbligatorio"],
                [
                    c("podman") + " (4.x, meglio 5.x)",
                    "esegue i container; SCARLET rileva da solo se è rootless o rootful",
                    "sì, salvo che si usi Docker o Kubernetes",
                ],
                [
                    c("podman-plugins") + ", " + c("fuse-overlayfs") + ", " + c("slirp4netns"),
                    "rete e storage in modalità rootless",
                    "sì con Podman rootless",
                ],
                [c("tar") + ", " + c("gzip"), "estrazione del pacchetto di rilascio", "sì"],
                [
                    c("coreutils"),
                    "fornisce "
                    + c("sha256sum")
                    + ", "
                    + c("ln")
                    + ", "
                    + c("mv")
                    + ", "
                    + c("df")
                    + ", "
                    + c("free")
                    + " e gli altri comandi di base",
                    "sì, già presente",
                ],
                [
                    c("curl"),
                    "health check HTTP eseguiti dall'host su " + c("127.0.0.1"),
                    "sì, se l'applicazione ha un health check HTTP",
                ],
                [
                    c("nmap-ncat") + " (fornisce " + c("nc") + ")",
                    "health check TCP e verifica delle porte in pre-flight",
                    "sì, se l'applicazione ha un health check TCP",
                ],
                [c("openssh-server"), "l'unico canale di accesso di SCARLET", "sì, già presente"],
            ],
            [24, 54, 22],
        ),
        P.space(6),
        P.callout(
            "Non serve installare Python, né un agente, né alcun pacchetto di SCARLET. Non serve "
            + c("sudo")
            + ": l'utente dedicato lavora esclusivamente dentro la propria home e dentro "
            + c("/opt/scarlet")
            + ".",
            "ok",
            title="Che cosa NON va installato",
        ),
        P.h2("Comandi che SCARLET esegue davvero"),
        P.para(
            "SCARLET non apre una shell interattiva e non costruisce righe di comando concatenando testo. Ogni "
            "comando è una lista di argomenti il cui eseguibile deve appartenere a una allow-list compilata nel "
            "codice. Questo è anche il modo più onesto di elencare i requisiti: se un binario non è in questa "
            "lista, SCARLET non può eseguirlo, e se manca sull'host il relativo passo fallisce con un errore "
            "esplicito. L'elenco completo è nell'Appendice A."
        ),
        P.code(
            [
                "# tracciato tipico di un rilascio, visibile nella pagina del deployment",
                "mkdir -p /opt/scarlet/applications/customer-api/releases",
                "sha256sum -- /opt/scarlet/applications/customer-api/staging/2.5.0.ab12cd34.scarlet.tar.gz",
                "tar --no-same-owner --no-same-permissions --no-overwrite-dir -xzf ... -C ...",
                "mv -T -- .../staging/2.5.0.extract .../releases/2.5.0",
                "podman pull registry.example.internal/team/customer-api:2.5.0",
                "ln -sfn -- .../releases/2.5.0 .../current.tmp && mv -T -- .../current.tmp .../current",
                "podman run -d --name customer-api --label scarlet.application=customer-api ...",
                "curl -k -s -S -o /dev/null -w %{http_code} --max-time 5 http://127.0.0.1:8080/health",
            ],
            title="Esempio reale",
        ),
        P.space(8),
        fig_layout_remoto(),
        P.caption(
            "Figura 2 — Il layout che SCARLET crea sotto /opt/scarlet. Tutto il resto del filesystem non viene toccato."
        ),
    ]

    # ============================= capitolo 3
    s += P.section("3. Server di destinazione: installazione", "c3")
    s += [
        P.para(
            "La preparazione di un host richiede pochi minuti e si fa una volta sola. Qui trovi prima lo script "
            "completo da copiare, poi la spiegazione di ogni singolo passo.",
            "lead",
        ),
        P.h2("Script completo, dalla macchina vuota"),
        P.code(
            [
                "#!/bin/bash",
                "# Preparazione di un server di destinazione SCARLET — Oracle Linux 9",
                "# Eseguire come root (o con sudo) una sola volta per host.",
                "set -euo pipefail",
                "",
                "SCARLET_USER=scarlet",
                "BASE_PATH=/opt/scarlet",
                "SCARLET_SERVER_IP=10.10.0.5        # indirizzo del server SCARLET",
                "",
                "# 1. pacchetti",
                "dnf install -y podman podman-plugins fuse-overlayfs slirp4netns \\",
                "               tar gzip coreutils curl nmap-ncat",
                "",
                "# 2. utente dedicato, senza sudo",
                'id -u "$SCARLET_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$SCARLET_USER"',
                "",
                "# 3. namespace utente per Podman rootless (se non già assegnati)",
                'grep -q "^${SCARLET_USER}:" /etc/subuid || \\',
                '  usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "$SCARLET_USER"',
                "",
                "# 4. i container sopravvivono alla chiusura della sessione SSH",
                'loginctl enable-linger "$SCARLET_USER"',
                "",
                "# 5. directory base",
                'mkdir -p "$BASE_PATH"',
                'chown "$SCARLET_USER:$SCARLET_USER" "$BASE_PATH"',
                'chmod 750 "$BASE_PATH"',
                "",
                "# 6. chiave pubblica di SCARLET (incollare qui la chiave generata sul server SCARLET)",
                'install -d -m 700 -o "$SCARLET_USER" -g "$SCARLET_USER" "/home/$SCARLET_USER/.ssh"',
                'cat > "/home/$SCARLET_USER/.ssh/authorized_keys" <<KEY',
                'from="${SCARLET_SERVER_IP}",no-agent-forwarding,no-port-forwarding,no-X11-forwarding ssh-ed25519 AAAA... scarlet',
                "KEY",
                'chown "$SCARLET_USER:$SCARLET_USER" "/home/$SCARLET_USER/.ssh/authorized_keys"',
                'chmod 600 "/home/$SCARLET_USER/.ssh/authorized_keys"',
                'restorecon -Rv "/home/$SCARLET_USER/.ssh" || true',
                "",
                "# 7. firewall: SSH solo dal server SCARLET, più le porte delle applicazioni",
                "firewall-cmd --permanent --add-rich-rule=\\",
                '  "rule family=ipv4 source address=${SCARLET_SERVER_IP}/32 service name=ssh accept"',
                "firewall-cmd --permanent --add-port=8080/tcp     # porta dell'applicazione",
                "firewall-cmd --reload",
                "",
                "# 8. fingerprint da confrontare in SCARLET al momento dell'approvazione",
                "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub",
            ],
            title="provisioning-host.sh",
        ),
        P.space(6),
        P.h2("Utente dedicato e Podman rootless"),
        P.para(
            "L'utente (chiamato "
            + c("scarlet")
            + " per convenzione, il nome è configurabile per ogni host) è un "
            "utente Linux ordinario e senza privilegi. Tre dettagli fanno la differenza fra un host che funziona "
            "e uno che si comporta in modo imprevedibile."
        ),
        *P.bullets(
            [
                b("subuid e subgid")
                + ": Podman rootless mappa gli utenti del container su un intervallo di UID "
                "dell'host. Se l'intervallo manca, il primo "
                + c("podman run")
                + " fallisce con "
                + c("newuidmap: Operation not permitted")
                + ". Su Oracle Linux 9 "
                + c("useradd")
                + " di norma li "
                "assegna da solo: il controllo nello script è una rete di sicurezza.",
                b("linger")
                + ": senza "
                + c("loginctl enable-linger")
                + " systemd chiude la sessione utente quando "
                "SCARLET chiude la connessione SSH, e con essa i container appena avviati. È l'errore più "
                "frequente e il più difficile da diagnosticare, perché il deployment risulta riuscito e "
                "l'applicazione sparisce qualche secondo dopo.",
                b("porte basse")
                + ": in modalità rootless le porte sotto la 1024 non sono utilizzabili. O si "
                "sceglie una porta applicativa uguale o superiore a 1024, oppure si abbassa il limite con "
                + c("sysctl net.ipv4.ip_unprivileged_port_start=80")
                + ", rendendolo persistente in "
                + c("/etc/sysctl.d/")
                + ".",
            ]
        ),
        P.space(4),
        P.callout(
            "SCARLET non usa mai "
            + c("sudo")
            + " e non lo richiede. Se la vostra policy impone Podman rootful, "
            "l'accesso SSH come root "
            + b("non è supportato")
            + ": va usato un utente che possa raggiungere il "
            "socket rootful secondo le regole aziendali. La modalità consigliata, e quella verificata, è rootless.",
            "warn",
            title="Niente sudo, niente root",
        ),
        P.h2("Chiave SSH e authorized_keys"),
        P.para(
            "La chiave privata viene generata "
            + b("sul server SCARLET")
            + " (ed25519) e caricata nella pagina "
            + c("Sicurezza › Credenziali")
            + ", dove viene cifrata con Fernet prima di essere scritta nel "
            "database. Sull'host si installa solo la parte pubblica. L'autenticazione a password è supportata "
            "per il primo avvio ma sconsigliata: la rotazione di una chiave si fa aggiungendo una credenziale "
            "nuova, che disattiva la precedente e lascia traccia nell'audit."
        ),
        P.para(
            "Le restrizioni in "
            + c("authorized_keys")
            + " non sono decorative. Il prefisso "
            + c('from="10.10.0.5"')
            + " impedisce l'uso della chiave da qualsiasi altro indirizzo, e le tre "
            "opzioni "
            + c("no-*")
            + " tolgono alla sessione la possibilità di aprire tunnel. Anche una chiave "
            "sottratta diventa così poco utile a un attaccante."
        ),
        P.h3("Approvazione del fingerprint dell'host"),
        P.para(
            "In produzione SCARLET rifiuta di collegarsi a un host la cui chiave non sia stata approvata da un "
            "amministratore ("
            + c("SCARLET_SSH_HOST_KEY_POLICY=strict")
            + "). La procedura corretta prevede di "
            "leggere il fingerprint "
            + b("sulla console del server")
            + ", non tramite la rete, e di confrontarlo "
            "con quello mostrato dalla console web."
        ),
        P.code(
            [
                "# sulla console del server di destinazione",
                "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub",
                "256 SHA256:5t0kV... root@app01 (ED25519)",
            ],
            title="Lettura fuori banda",
        ),
        P.space(5),
        P.callout(
            "Cambiare hostname, indirizzo IP o porta SSH di un host invalida l'approvazione: la chiave va "
            "riapprovata. Una chiave diversa da quella approvata blocca l'host, lo segna OFFLINE e genera un "
            "evento di sicurezza CRITICAL. È il comportamento voluto: prima di riapprovare occorre accertarsi "
            "che il server sia stato davvero reinstallato.",
            "danger",
            title="Quando il fingerprint cambia",
        ),
        P.h2("SELinux e firewall locale"),
        P.para(
            "SELinux resta in modalità "
            + b("enforcing")
            + ". SCARLET monta i volumi dei container con l'opzione "
            + c(":Z")
            + ", che delega a Podman la rietichettatura, quindi non serve alcuna deroga. Se compare un "
            "diniego, la risposta non è disattivare SELinux ma correggere l'etichetta."
        ),
        P.code(
            [
                "ausearch -m avc -ts recent                 # che cosa è stato negato",
                "restorecon -Rv /opt/scarlet                # rimette a posto le etichette",
                "restorecon -Rv /home/scarlet/.ssh          # tipico dopo aver copiato authorized_keys a mano",
            ]
        ),
        P.space(5),
        P.para(
            "Sul firewall dell'host servono due sole cose: la porta SSH raggiungibile "
            + b("solo")
            + " dal server "
            "SCARLET e le porte con cui gli utenti raggiungono le applicazioni. Nient'altro va aperto in ingresso."
        ),
    ]

    # ============================= capitolo 4
    s += P.section("4. Verifica prima di consegnare l'host", "c4")
    s += [
        P.para(
            "Questi controlli si eseguono sull'host come utente "
            + c("scarlet")
            + " e richiedono meno di un "
            "minuto. Se tutti danno l'esito atteso, la registrazione in SCARLET andrà a buon fine al primo "
            "tentativo.",
            "lead",
        ),
        P.code(
            [
                "sudo -iu scarlet          # entrare nel contesto dell'utente dedicato",
                "",
                "podman info --format '{{.Host.Security.Rootless}}'   # atteso: true",
                "podman run --rm docker.io/library/busybox echo ok    # atteso: ok",
                'for x in tar gzip sha256sum curl nc ln readlink df free nproc; do command -v $x >/dev/null || echo "MANCA $x"; done',
                "test -w /opt/scarlet && echo 'scrittura ok'",
                "loginctl show-user scarlet --property=Linger          # atteso: Linger=yes",
                "grep '^scarlet:' /etc/subuid /etc/subgid              # atteso: due righe",
                "getenforce                                            # atteso: Enforcing",
            ],
            title="Controlli sull'host",
        ),
        P.space(6),
        P.para("Dal server SCARLET, invece, si verifica il canale end-to-end:"),
        P.code(
            [
                "ssh -i /percorso/chiave -o BatchMode=yes scarlet@app01 'id; podman --version'",
                "# deve rispondere senza chiedere password e senza chiedere conferma del fingerprint",
            ]
        ),
        P.space(6),
        P.para(
            "L'ultima verifica si fa dalla console web e coincide con le azioni "
            + b("Test connessione")
            + " e "
            + b("Discover")
            + " nella pagina dell'host. La prima apre la "
            "connessione e misura la latenza, la seconda raccoglie sistema operativo, runtime, versione, "
            "memoria e disco, e compila la scheda dell'host. Se Discover riporta runtime "
            + c("NONE")
            + ", "
            "il runtime non è installato oppure l'utente non riesce a eseguirlo."
        ),
        P.space(4),
        P.table(
            [
                ["Controllo", "Esito atteso", "Se fallisce"],
                [
                    "Test connessione",
                    "ONLINE, con latenza in millisecondi",
                    "chiave, utente, firewall o fingerprint non approvato",
                ],
                [
                    "Discover",
                    "sistema operativo e runtime rilevati, disco e memoria valorizzati",
                    "runtime assente o non eseguibile dall'utente",
                ],
                [
                    "Stato chiave host",
                    "APPROVED",
                    "eseguire Scan host key e approvare dopo il confronto fuori banda",
                ],
                [
                    "Pre-flight di un deployment di prova",
                    "tutti i controlli verdi",
                    "leggere il controllo rosso: indica esattamente la causa",
                ],
            ],
            [22, 38, 40],
        ),
    ]

    # ============================= capitolo 5
    s += P.section("5. Varianti: Docker e Kubernetes", "c5")
    s += [
        P.para(
            "Podman è la scelta consigliata su Oracle Linux, ma gli altri due runtime sono supportati con lo "
            "stesso identico flusso di lavoro: cambia l'adattatore usato da SCARLET, non la procedura operativa.",
            "lead",
        ),
        P.h2("Docker Engine"),
        P.code(
            [
                "# repository ufficiale Docker su Oracle Linux",
                "sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo",
                "sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin \\",
                "                    tar gzip curl nmap-ncat",
                "sudo systemctl enable --now docker",
                "sudo usermod -aG docker scarlet      # l'utente deve poter parlare con il socket",
            ]
        ),
        P.space(5),
        P.callout(
            "Appartenere al gruppo "
            + c("docker")
            + " equivale, di fatto, ad avere root sull'host: chi può "
            "parlare con il socket può montare qualunque percorso dentro un container. È la ragione principale "
            "per cui su Oracle Linux consigliamo Podman rootless, che non richiede alcun privilegio aggiuntivo.",
            "warn",
            title="Il prezzo del gruppo docker",
        ),
        P.h2("Kubernetes"),
        P.para(
            "Per i cluster ci sono due modalità. Nella prima l'host registrato in SCARLET è una macchina con "
            + c("kubectl")
            + " già configurato, e SCARLET lo comanda via SSH esattamente come fa con Podman: "
            "serve solo la porta 22. Nella seconda SCARLET parla direttamente con l'API server usando un "
            "kubeconfig caricato come credenziale, e in quel caso occorre aprire la 6443 dal server SCARLET "
            "verso il cluster."
        ),
        P.table(
            [
                ["Modalità", "Da installare sull'host", "Porte", "Quando sceglierla"],
                [
                    b("kubectl via SSH"),
                    c("kubectl") + " 1.27+ con kubeconfig valido per l'utente " + c("scarlet"),
                    "22/tcp",
                    "quando esiste già una bastion host verso il cluster",
                ],
                [
                    b("API diretta"),
                    "nessuna macchina intermedia: il kubeconfig è una credenziale in SCARLET",
                    "6443/tcp",
                    "quando il control plane raggiunge l'API server in rete",
                ],
            ],
            [16, 40, 12, 32],
        ),
        P.space(5),
        P.para(
            "In modalità API non va installato "
            + b("nulla")
            + ", da nessuna parte: non serve una macchina "
            "intermedia, non serve un utente Linux, non c'è un fingerprint da approvare e non viene creata "
            "alcuna directory sui nodi. SCARLET applica gli oggetti nel namespace e pubblica la "
            "configurazione come Secret. È la modalità consigliata quando il control plane raggiunge l'API "
            "server in rete."
        ),
        P.space(4),
        P.h3("Permessi richiesti alla credenziale"),
        P.para(
            "Un Role limitato al namespace, non "
            + c("cluster-admin")
            + ". Serve "
            + c("get list watch create update patch delete")
            + " sugli oggetti che il pacchetto installa "
            "(Deployment, Service, ConfigMap, Secret, Ingress e simili), "
            + c("get list")
            + " sui pod, "
            + c("get")
            + " su "
            + c("pods/log")
            + " per i log e "
            + c("get list")
            + " sugli eventi, che sono "
            "ciò che spiega un rollout fallito. Solo se SCARLET deve creare il namespace serve anche "
            + c("get create")
            + " su "
            + c("namespaces")
            + ", che è di ambito cluster."
        ),
        P.space(4),
        P.callout(
            "Gli oggetti RBAC di cluster ("
            + c("ClusterRole")
            + ", "
            + c("ClusterRoleBinding")
            + ") e le "
            "definizioni di risorse personalizzate non possono essere installati da un pacchetto: assegnarli "
            "è competenza del team di piattaforma, non di un rilascio applicativo. Un pacchetto che li "
            "contiene viene respinto con un messaggio che nomina il tipo.",
            "warn",
            title="Quello che un pacchetto non può installare",
        ),
    ]

    # ============================= capitolo 6
    s += P.section("6. Il server SCARLET (control plane)", "c6")
    s += [
        P.para(
            "Una sola macchina ospita l'intero control plane. Tutti i componenti girano come container di un "
            "unico compose: non si installa Python, né PostgreSQL, né nginx sul sistema operativo.",
            "lead",
        ),
        P.table(
            [
                ["Voce", "Minimo", "Consigliato"],
                ["CPU / RAM", "2 vCPU / 4 GB", "4 vCPU / 8 GB"],
                [
                    "Disco",
                    "40 GB",
                    "100 GB o più, con volume separato per " + c("/var/lib/scarlet"),
                ],
                ["Sistema operativo", "Oracle Linux 8.8, SELinux enforcing", "Oracle Linux 9.x"],
                [
                    "Rete in ingresso",
                    "443/tcp dagli operatori",
                    "443/tcp; la 80 solo per il redirect",
                ],
                [
                    "Rete in uscita",
                    "22/tcp verso ogni host gestito",
                    "più 587/tcp se si abilitano le e-mail",
                ],
            ],
            [20, 38, 42],
        ),
        P.space(6),
        P.code(
            [
                "# 1. runtime e utilità",
                "sudo dnf install -y podman podman-compose git tar policycoreutils-python-utils firewalld",
                "",
                "# 2. utente e directory dei dati",
                "sudo useradd -r -m -d /opt/scarlet-server -s /bin/bash scarlet",
                "sudo mkdir -p /var/lib/scarlet/{postgres,redis,data,nginx-logs} /opt/scarlet-server/tls",
                "sudo chown -R scarlet:scarlet /opt/scarlet-server /var/lib/scarlet",
                "",
                "# 3. configurazione: due chiavi DIVERSE, da custodire nel vault aziendale",
                "cd /opt/scarlet-server && cp .env.example .env && chmod 600 .env",
                "podman run --rm scarlet:1.0.0 flask scarlet gen-key   # SCARLET_SECRET_KEY",
                "podman run --rm scarlet:1.0.0 flask scarlet gen-key   # SCARLET_CREDENTIAL_ENCRYPTION_KEY",
                "",
                "# 4. avvio come servizio di sistema",
                "sudo cp deployment/systemd/scarlet.service /etc/systemd/system/",
                "sudo systemctl daemon-reload && sudo systemctl enable --now scarlet",
                "",
                "# 5. verifica",
                "curl -k https://scarlet.example.internal/api/ready",
            ],
            title="Installazione del control plane",
        ),
        P.space(6),
        P.callout(
            "Senza "
            + c("SCARLET_CREDENTIAL_ENCRYPTION_KEY")
            + " un backup del database è inutilizzabile: le "
            "credenziali SSH e i segreti non sono più decifrabili. Le due chiavi vanno nel vault aziendale "
            + b("prima")
            + " di mettere il sistema in esercizio, e "
            + c("SCARLET_INITIAL_ADMIN_PASSWORD")
            + " va "
            "rimossa dal file " + c(".env") + " dopo il primo avvio.",
            "danger",
            title="Le due chiavi non si recuperano",
        ),
        P.space(4),
        P.para(
            "Il certificato TLS va in "
            + c("/opt/scarlet-server/tls/")
            + " con permessi 0600. SCARLET non serve "
            "mai HTTP in chiaro in produzione: nginx reindirizza la 80 sulla 443 e il cookie di sessione è "
            "marcato "
            + c("Secure")
            + ". I dettagli completi, comprese le installazioni senza rete e la "
            "procedura di aggiornamento, sono in " + c("docs/installation.md") + "."
        ),
    ]

    # ============================= capitolo 7
    s += P.section("7. Postazioni e macchine di build", "c7")
    s += [
        P.h2("PC degli operatori"),
        P.para(
            "Nulla da installare. Serve un browser aggiornato (Chrome, Edge o Firefox) e le credenziali "
            "personali. Chi automatizza da script usa un token API personale e un qualsiasi client HTTP: "
            "il token eredita i permessi dell'utente ed è tracciato nell'audit con il suo nome."
        ),
        P.h2("PC o pipeline del team applicativo"),
        P.para(
            "Serve solo a chi confeziona i pacchetti, non a chi li distribuisce. Il pacchetto è un "
            + c("tar.gz")
            + " con un manifest: può essere prodotto dallo script incluso nel repository oppure "
            "da qualunque strumento che rispetti il contratto."
        ),
        P.table(
            [
                ["Da installare", "Perché"],
                ["Docker o Podman", "costruire l'immagine dell'applicazione"],
                [
                    c("docker save") + " / " + c("podman save"),
                    "solo se l'immagine viaggia dentro il pacchetto, per gli host senza accesso al registry",
                ],
                [
                    "Python 3.12+ e il repository SCARLET",
                    "per "
                    + c("scripts/build-scarlet-package.py")
                    + ", che valida il pacchetto con le stesse regole dell'upload",
                ],
            ],
            [30, 70],
        ),
        P.space(5),
        P.callout(
            "Far girare il packager nella pipeline conviene: applica gli stessi controlli che SCARLET eseguirà "
            "al caricamento (schema del manifest, percorsi, link, dimensioni), quindi gli errori emergono nella "
            "build del team e non davanti all'operatore che sta rilasciando.",
            "info",
        ),
        P.h2("PC di sviluppo di SCARLET"),
        P.para(
            "Riguarda solo chi modifica SCARLET stesso: Docker Desktop o Podman Desktop con compose, Python "
            "3.12+ e git. Il comando "
            + c("docker compose --profile dev up -d --build")
            + " avvia l'intero "
            "ambiente, inclusi due server Oracle Linux simulati con Podman per le prove di DEV e PROD."
        ),
    ]

    # ============================= capitolo 8
    s += P.section("8. Matrice dei flussi di rete", "c8")
    s += [
        P.para(
            "La tabella elenca tutti i flussi, compresi quelli opzionali. Le righe obbligatorie sono due: gli "
            "operatori verso SCARLET e SCARLET verso gli host. Tutto il resto dipende da come è configurato "
            "l'ambiente.",
            "lead",
        ),
        fig_flussi(),
        P.caption("Figura 3 — I flussi principali. Le linee tratteggiate sono opzionali."),
        P.space(8),
        P.table(
            [
                ["Da", "Verso", "Porta", "Scopo", "Obbl."],
                [
                    "Browser degli operatori",
                    "Server SCARLET",
                    "443/tcp<br/>80/tcp solo redirect",
                    "console web e API",
                    "sì",
                ],
                [
                    "Server SCARLET<br/>(container web e worker)",
                    "ogni server di destinazione",
                    "22/tcp<br/>o la porta SSH configurata",
                    "SSH e SFTP: deploy, operazioni di ciclo di vita, discover, riconciliazione, log",
                    "sì",
                ],
                [
                    "Server SCARLET",
                    "API server Kubernetes",
                    "6443/tcp",
                    "solo host Kubernetes in modalità API; con kubectl via SSH basta la 22",
                    "no",
                ],
                [
                    "Server di destinazione",
                    "registry delle immagini",
                    "443/tcp",
                    c("podman pull") + " quando l'immagine non viaggia dentro il pacchetto",
                    "no",
                ],
                [
                    "Server di destinazione",
                    "dipendenze applicative<br/>(database, code, API)",
                    "specifiche dell'app",
                    "le applicazioni distribuite, non SCARLET",
                    "dipende",
                ],
                [
                    "Utenti e sistemi client",
                    "server di destinazione",
                    "porte delle applicazioni",
                    "uso normale delle applicazioni distribuite",
                    "sì",
                ],
                [
                    "Server SCARLET",
                    "relay SMTP",
                    "587/tcp<br/>oppure 25 o 465",
                    "notifiche e-mail, solo se abilitate",
                    "no",
                ],
                [
                    "Sistema di monitoraggio",
                    "Server SCARLET",
                    "443/tcp",
                    c("/api/metrics") + ", " + c("/api/health") + ", " + c("/api/ready"),
                    "no",
                ],
                [
                    "Server SCARLET",
                    "repository del sistema operativo e registry",
                    "443/tcp",
                    "installazione e aggiornamenti del control plane",
                    "in fase di installazione",
                ],
                [
                    "Server SCARLET",
                    "cdn.jsdelivr.net",
                    "443/tcp",
                    "asset grafici in modalità CDN; non serve con " + c("SCARLET_ASSET_MODE=local"),
                    "no",
                ],
            ],
            [17, 17, 14, 42, 10],
            font_size=8.2,
        ),
        P.space(6),
        P.callout(
            "Due conseguenze pratiche che fanno risparmiare regole inutili. Primo: gli health check delle "
            "applicazioni partono "
            + b("dal server di destinazione stesso")
            + " verso "
            + c("127.0.0.1")
            + ", "
            "quindi non serve alcun flusso da SCARLET verso le porte applicative. Secondo: i server di "
            "destinazione non devono mai raggiungere SCARLET, in nessuna circostanza.",
            "ok",
            title="Quello che non serve aprire",
        ),
        P.space(4),
        P.para(
            "I flussi interni al server SCARLET (nginx verso gunicorn sulla 8000, gunicorn e worker verso "
            "PostgreSQL sulla 5432 e Redis sulla 6379) restano dentro la rete dei container e non richiedono "
            "alcuna regola sul firewall."
        ),
    ]

    # ============================= capitolo 9
    s += P.section("9. Errori tipici e come risolverli", "c9")
    s += [
        P.para(
            "Sono i casi che si incontrano davvero durante la preparazione di un host, con il messaggio "
            "esatto da cercare nei log e la correzione.",
            "lead",
        ),
        P.table(
            [
                ["Sintomo o messaggio", "Causa", "Rimedio"],
                [
                    c("newuidmap: Operation not permitted"),
                    "l'utente non ha intervalli subuid/subgid",
                    c("usermod --add-subuids 100000-165535 --add-subgids 100000-165535 scarlet")
                    + ", poi "
                    + c("podman system migrate"),
                ],
                [
                    "il container sparisce pochi secondi dopo un deployment riuscito",
                    "manca il linger: systemd chiude la sessione utente",
                    c("loginctl enable-linger scarlet"),
                ],
                [
                    c("stat /home/scarlet/.config: no such file or directory"),
                    "directory XDG mancanti alla prima esecuzione rootless",
                    "creare "
                    + c(".config")
                    + ", "
                    + c(".local/share")
                    + " e assicurarsi che "
                    + c("XDG_RUNTIME_DIR")
                    + " sia valorizzato nella sessione",
                ],
                [
                    c("controller 'pids' is not available"),
                    "cgroup non disponibili, tipico degli host annidati o dei container di prova",
                    "impostare "
                    + c('cgroups = "disabled"')
                    + " in "
                    + c("~/.config/containers/containers.conf")
                    + "; su un host fisico o virtuale normale non serve",
                ],
                [
                    "Discover riporta runtime " + c("NONE"),
                    "il runtime non è installato o l'utente non riesce a eseguirlo",
                    "verificare con "
                    + c("sudo -iu scarlet podman info")
                    + "; con Docker controllare l'appartenenza al gruppo",
                ],
                [
                    "Test connessione fallisce con errore di autenticazione",
                    "chiave non installata, permessi errati o restrizione "
                    + c("from=")
                    + " non corrispondente",
                    c("chmod 700 ~/.ssh; chmod 600 authorized_keys")
                    + "; "
                    + c("restorecon -Rv ~scarlet/.ssh")
                    + "; verificare l'IP di origine",
                ],
                [
                    "stato della chiave host " + c("MISMATCH"),
                    "la chiave del server è cambiata: reinstallazione oppure attacco",
                    "accertare la causa fuori banda; solo se legittima, riapprovare il nuovo fingerprint",
                ],
                [
                    "pre-flight rosso su " + c("disk") + " o " + c("memory"),
                    "risorse libere inferiori a quelle richieste dal manifest",
                    "liberare spazio ("
                    + c("podman image prune -a")
                    + ") o rivedere i requisiti dichiarati",
                ],
                [
                    "pre-flight rosso su " + c("ports"),
                    "la porta dell'applicazione è già occupata sull'host",
                    "liberare la porta o cambiarla nel manifest; in rootless ricordare il limite delle porte sotto la 1024",
                ],
                [
                    c("permission denied") + " sui volumi del container",
                    "proprietà o etichetta SELinux errate",
                    "correggere il proprietario e lasciare che SCARLET monti con "
                    + c(":Z")
                    + "; "
                    + c("restorecon -Rv /opt/scarlet"),
                ],
                [
                    c("no space left on device") + " durante il rilascio",
                    "storage delle immagini pieno",
                    c("podman system df")
                    + " per capire, poi "
                    + c("podman image prune -a --filter until=168h"),
                ],
            ],
            [26, 26, 48],
            font_size=8.3,
        ),
    ]

    # ============================= capitolo 10
    s += P.section("10. Checklist di consegna", "c10")
    s += [
        P.para(
            "Da allegare alla consegna di ogni server di destinazione. Se tutte le voci sono spuntate, l'host "
            "può essere registrato in SCARLET e usato per un rilascio.",
            "lead",
        ),
        P.table(
            [
                ["Fatto", "Voce", "Come si verifica"],
                [
                    c("[  ]"),
                    "Sistema operativo supportato e aggiornato",
                    c("cat /etc/oracle-release"),
                ],
                [
                    c("[  ]"),
                    "Runtime installato e funzionante per l'utente dedicato",
                    c("sudo -iu scarlet podman run --rm busybox echo ok"),
                ],
                [
                    c("[  ]"),
                    "Utilità presenti: tar, gzip, sha256sum, curl, nc",
                    c("command -v tar gzip sha256sum curl nc"),
                ],
                [c("[  ]"), "Utente dedicato creato, senza sudo", c("id scarlet")],
                [
                    c("[  ]"),
                    "subuid e subgid assegnati",
                    c("grep '^scarlet:' /etc/subuid /etc/subgid"),
                ],
                [c("[  ]"), "Linger abilitato", c("loginctl show-user scarlet --property=Linger")],
                [
                    c("[  ]"),
                    "Directory base scrivibile",
                    c("sudo -iu scarlet test -w /opt/scarlet && echo ok"),
                ],
                [
                    c("[  ]"),
                    "Chiave pubblica installata con restrizione " + c("from="),
                    c("cat ~scarlet/.ssh/authorized_keys"),
                ],
                [c("[  ]"), "SELinux enforcing", c("getenforce")],
                [
                    c("[  ]"),
                    "Firewall: SSH consentita solo dal server SCARLET",
                    c("firewall-cmd --list-all"),
                ],
                [
                    c("[  ]"),
                    "Porte applicative aperte verso gli utenti",
                    c("firewall-cmd --list-ports"),
                ],
                [
                    c("[  ]"),
                    "Fingerprint annotato e comunicato a chi lo approverà",
                    c("ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub"),
                ],
                [c("[  ]"), "Orologio sincronizzato", c("timedatectl")],
                [
                    c("[  ]"),
                    "Test connessione e Discover riusciti dalla console web",
                    "pagina dell'host in SCARLET",
                ],
            ],
            [5, 45, 50],
        ),
        P.space(8),
        P.para(
            "Host: ________________________________     Ambiente: ______________     Data: ______________",
            "small",
        ),
        P.space(3),
        P.para(
            "Preparato da: ________________________     Verificato da: ________________________",
            "small",
        ),
    ]

    # ============================= appendice A
    s += P.section("Appendice A. Elenco completo dei binari richiesti", "ca")
    s += [
        P.para(
            "Questa è la allow-list compilata dentro SCARLET: nessun altro eseguibile può essere invocato su un "
            "host, nemmeno da un amministratore. Serve come elenco esatto di ciò che deve esistere sul server e "
            "come garanzia sul perimetro delle operazioni.",
            "lead",
        ),
        P.table(
            [
                ["Gruppo", "Binari", "Fornito da", "Uso"],
                [
                    "Ispezione, sola lettura",
                    c(
                        "cat uname nproc free df id hostname readlink ls stat test sha256sum command which systemctl getenforce true"
                    ),
                    "coreutils, systemd, policycoreutils",
                    "Discover, pre-flight, verifica dei checksum",
                ],
                [
                    "Filesystem, solo sotto la directory base",
                    c("mkdir mv rm ln tar cp chmod"),
                    "coreutils, tar",
                    "preparazione del layout, estrazione, attivazione della release",
                ],
                [
                    "Runtime dei container",
                    c("podman docker kubectl helm"),
                    "il runtime scelto",
                    "install, start, stop, restart, logs, stato, rollback",
                ],
                [
                    "Health check",
                    c("curl nc"),
                    "curl, nmap-ncat",
                    "sonde HTTP e TCP eseguite dall'host su 127.0.0.1",
                ],
                [
                    "Uso ristretto",
                    c("sh timeout find"),
                    "coreutils, findutils",
                    "utilizzabili solo attraverso costruttori interni con forma fissa degli argomenti",
                ],
            ],
            [18, 34, 20, 28],
            font_size=8.3,
        ),
        P.space(6),
        P.callout(
            "Su un'installazione minima di Oracle Linux mancano normalmente solo "
            + c("nc")
            + " (pacchetto "
            + c("nmap-ncat")
            + ") e il runtime. Tutto il resto è già presente. "
            + c("getenforce")
            + " viene usato "
            "se disponibile e la sua assenza non è un errore.",
            "info",
        ),
    ]

    # ============================= appendice B
    s += P.section("Appendice B. Documenti di riferimento", "cb")
    s += [
        P.table(
            [
                ["Documento", "Contenuto"],
                [
                    c("docs/installation.md"),
                    "installazione completa del control plane, TLS, systemd, backup, aggiornamenti, installazioni senza rete",
                ],
                [
                    c("docs/ssh.md"),
                    "requisiti dell'utente remoto, autenticazione, verifica della chiave host, parametri di connessione",
                ],
                [
                    c("docs/runtime-podman.md"),
                    "Podman rootless e rootful, riavvio dopo il reboot, storage e pulizia",
                ],
                [c("docs/runtime-docker.md"), "specificità di Docker Engine"],
                [
                    c("docs/runtime-kubernetes.md"),
                    "modalità kubectl e API, permessi del service account",
                ],
                [
                    c("docs/RUNBOOK.md"),
                    "31 procedure operative numerate con precondizioni, errori possibili e ripristino",
                ],
                [
                    c("docs/APPLICATION_RELEASE_CONTRACT.md"),
                    "contratto del pacchetto e schema del manifest per i team applicativi",
                ],
                [c("docs/security.md"), "modello delle minacce e controlli"],
                [
                    "Guida utente in linea",
                    "voce "
                    + b("Guida utente")
                    + " nel menu: procedura completa dall'host vuoto all'applicazione online",
                ],
            ],
            [30, 70],
        ),
        P.space(8),
        P.para(
            "Questo documento è generato dal repository di SCARLET con "
            + c("python scripts/build_pdf_docs.py")
            + ", così resta allineato al codice: l'elenco dei binari, i percorsi e i parametri provengono dalle "
            "stesse fonti usate dall'applicazione.",
            "small",
        ),
    ]
    return s


META = P.DocMeta(
    title="Requisiti delle macchine\nper il deploy",
    subtitle="Che cosa installare, dove e perché",
    kicker="Manuale di installazione",
    version=VERSION,
    date=date.today().strftime("%d/%m/%Y"),
    audience="Sistemisti, team infrastruttura, gestione firewall",
    summary=(
        "SCARLET distribuisce applicazioni su server Oracle Linux remoti senza installare alcun agente. "
        "Questo manuale elenca, per ogni tipo di macchina coinvolta, il software da installare, l'utente da "
        "creare, le porte da aprire e i controlli da eseguire prima di dichiarare un server pronto. "
        "Include lo script di preparazione completo, la matrice dei flussi di rete e la checklist di consegna."
    ),
    filename="SCARLET-Requisiti-Macchine-Deploy.pdf",
    highlights=(
        "Che cosa installare su ogni server di destinazione, con i comandi verificati",
        "Lo script di preparazione completo, dalla macchina vuota all'host pronto",
        "Utente dedicato, chiave SSH, approvazione del fingerprint, SELinux e firewall",
        "La matrice completa dei flussi di rete, con le porte obbligatorie e quelle opzionali",
        "Gli errori tipici con il messaggio esatto e il rimedio",
        "La checklist di consegna da allegare a ogni server",
    ),
)


def main() -> Path:
    return P.build(META, story())


if __name__ == "__main__":
    print(main())
