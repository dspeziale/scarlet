"""Lightweight i18n for the SCARLET probe UI (English / Italian).

The chosen language is persisted in the probe state file. `make_translator(lang)`
returns a `t(key)` bound to a language, falling back to English then the key.
"""

DEFAULT_LANG = "en"
LANGUAGES = {
    "en": {"label": "English", "flag": "🇬🇧"},
    "it": {"label": "Italiano", "flag": "🇮🇹"},
}

TRANSLATIONS = {
    "en": {
        # nav / chrome
        "nav.section.overview": "OVERVIEW",
        "nav.section.modules": "MODULES",
        "nav.dashboard": "Dashboard",
        "nav.scanner": "Network Scanner",
        "nav.suricata": "Suricata IDS",
        "nav.wireless": "Wireless (WiFi/BLE)",
        "nav.guide": "Guide",
        "hdr.guide": "Probe Guide",
        "footer.rights": "All rights reserved.",
        # LED states
        "led.connecting": "Connecting…",
        "led.online": "Online with Server",
        "led.unreachable": "Server Unreachable",
        "led.not_paired": "Not Paired",
        "led.offline": "Offline",
        # page headers
        "hdr.overview": "Probe Overview",
        "hdr.scanner": "Network Scanner",
        "hdr.suricata": "Suricata Intrusion Detection",
        "hdr.wireless": "Wireless Discovery",
        # status hero
        "conn.status": "Connection Status",
        "conn.paired": "Paired & Secured",
        "conn.pending": "Pending",
        "conn.not_connected": "Not Connected",
        "conn.paired_sub": "End-to-end encrypted channel active · auto-scan every 30 min",
        "conn.register_sub": "Register this probe with a License Code to begin scanning",
        # tiles
        "tile.probe_id": "Probe ID",
        "tile.subnet": "Target Subnet",
        "tile.encryption": "Encryption",
        "tile.autoscan": "Auto Scan",
        "tile.autoscan_val": "Every 30 min",
        # actions / sections
        "act.quick_actions": "Quick Actions",
        "act.danger_zone": "Danger Zone",
        "act.factory_reset": "Factory Reset Probe",
        "act.reset_warn": "Resetting the probe removes all local cryptographic keys and pairings. You will need a new License Code to connect again.",
        "act.register": "Register Probe",
        "act.connect": "Connect to Server",
        # form labels
        "form.probe_name": "Probe Name",
        "form.geo_contact": "Geographic & Contact Info (Optional)",
        "form.address": "Physical Address",
        "form.coords": "Coordinates (Lat, Long)",
        "form.contact": "Contact Person",
        "form.email": "Email Alerts",
        "form.telegram": "Telegram ID",
        "form.auth": "Authentication",
        "form.tenant": "Tenant Name or ID",
        "form.license": "License Code",
        # scanner
        "scan.manual": "Manual Scan Trigger",
        "scan.manual_desc": "The probe automatically scans the network every 30 minutes. To force an immediate scan, click below.",
        "scan.force": "Force Network Scan",
        "scan.config": "Scanner Configuration",
        "scan.subnet": "Target Subnet (CIDR format)",
        "scan.save": "Save Configuration",
        "scan.status": "Scanner Status",
        "scan.logs": "Scan Debug Logs",
        "scan.refresh": "Refresh",
        # suricata
        "ids.control": "IDS Control",
        "ids.interface": "Capture Interface",
        "ids.start": "Start",
        "ids.stop": "Stop",
        "ids.feed": "Live Packet / Event Feed",
        "ids.engine": "Engine",
        "ids.active": "IDS active",
        "ids.off": "IDS off",
        # wireless
        "wl.wifi": "WiFi Scan",
        "wl.ble": "BLE Scan",
        "wl.scan": "Scan",
        "wl.no_scan": "No scan yet.",
        # common
        "common.language": "Language",
        "common.status": "Status",
        "lbl.interface": "Interface",
        "wl.ch": "Ch",
        "wl.sec": "Sec",
    },
    "it": {
        "nav.section.overview": "PANORAMICA",
        "nav.section.modules": "MODULI",
        "nav.dashboard": "Dashboard",
        "nav.scanner": "Scanner di Rete",
        "nav.suricata": "Suricata IDS",
        "nav.wireless": "Wireless (WiFi/BLE)",
        "nav.guide": "Guida",
        "hdr.guide": "Guida Sonda",
        "footer.rights": "Tutti i diritti riservati.",
        "led.connecting": "Connessione…",
        "led.online": "Online con il Server",
        "led.unreachable": "Server Irraggiungibile",
        "led.not_paired": "Non Accoppiata",
        "led.offline": "Offline",
        "hdr.overview": "Panoramica Sonda",
        "hdr.scanner": "Scanner di Rete",
        "hdr.suricata": "Rilevamento Intrusioni Suricata",
        "hdr.wireless": "Rilevamento Wireless",
        "conn.status": "Stato Connessione",
        "conn.paired": "Accoppiata e Protetta",
        "conn.pending": "In attesa",
        "conn.not_connected": "Non Connessa",
        "conn.paired_sub": "Canale cifrato end-to-end attivo · scansione automatica ogni 30 min",
        "conn.register_sub": "Registra questa sonda con un Codice Licenza per iniziare le scansioni",
        "tile.probe_id": "ID Sonda",
        "tile.subnet": "Subnet di Destinazione",
        "tile.encryption": "Cifratura",
        "tile.autoscan": "Scansione Auto",
        "tile.autoscan_val": "Ogni 30 min",
        "act.quick_actions": "Azioni Rapide",
        "act.danger_zone": "Zona Pericolosa",
        "act.factory_reset": "Ripristino di Fabbrica",
        "act.reset_warn": "Il ripristino rimuove tutte le chiavi crittografiche locali e gli accoppiamenti. Servirà un nuovo Codice Licenza per riconnettersi.",
        "act.register": "Registra Sonda",
        "act.connect": "Connetti al Server",
        "form.probe_name": "Nome Sonda",
        "form.geo_contact": "Informazioni Geografiche e di Contatto (Opzionale)",
        "form.address": "Indirizzo Fisico",
        "form.coords": "Coordinate (Lat, Long)",
        "form.contact": "Persona di Contatto",
        "form.email": "Avvisi Email",
        "form.telegram": "ID Telegram",
        "form.auth": "Autenticazione",
        "form.tenant": "Nome o ID Tenant",
        "form.license": "Codice Licenza",
        "scan.manual": "Avvio Scansione Manuale",
        "scan.manual_desc": "La sonda scansiona la rete automaticamente ogni 30 minuti. Per forzare una scansione immediata, clicca qui sotto.",
        "scan.force": "Forza Scansione di Rete",
        "scan.config": "Configurazione Scanner",
        "scan.subnet": "Subnet di Destinazione (formato CIDR)",
        "scan.save": "Salva Configurazione",
        "scan.status": "Stato Scanner",
        "scan.logs": "Log di Debug Scansione",
        "scan.refresh": "Aggiorna",
        "ids.control": "Controllo IDS",
        "ids.interface": "Interfaccia di Cattura",
        "ids.start": "Avvia",
        "ids.stop": "Ferma",
        "ids.feed": "Feed Pacchetti / Eventi Live",
        "ids.engine": "Motore",
        "ids.active": "IDS attivo",
        "ids.off": "IDS spento",
        "wl.wifi": "Scansione WiFi",
        "wl.ble": "Scansione BLE",
        "wl.scan": "Scansiona",
        "wl.no_scan": "Nessuna scansione ancora.",
        "common.language": "Lingua",
        "common.status": "Stato",
        "lbl.interface": "Interfaccia",
        "wl.ch": "Can",
        "wl.sec": "Sic",
    },
}


def make_translator(lang):
    if lang not in LANGUAGES:
        lang = DEFAULT_LANG
    table = TRANSLATIONS.get(lang, {})
    en = TRANSLATIONS[DEFAULT_LANG]

    def t(key):
        return table.get(key) or en.get(key, key)
    return t
