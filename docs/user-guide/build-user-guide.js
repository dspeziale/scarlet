// Scarlet - Guida utente (docx). Font: PT Sans Narrow (incorporato).
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Footer, Header, PageNumber,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle, TableOfContents, LevelFormat,
  PageBreak,
  TableLayoutType, VerticalAlign, Tab, TabStopType,
} = require('docx');

const VERSION = '1.0.0';
const FONT = 'PT Sans Narrow';
const MONO = 'Consolas';
const RED = 'A4161A';
const DARK = '2B2B2B';
const GREY = '5F6B7A';
const LIGHT = 'F4F1F1';
const CONTENT_W = 9638; // A4 con margini di 2 cm

// ------------------------------------------------------------------ helpers
function runs(text, base = {}) {
  // **grassetto**, `codice`, _corsivo_
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|_[^_]+_)/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    if (t.startsWith('**')) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...base }));
    else if (t.startsWith('`')) out.push(new TextRun({ text: t.slice(1, -1), font: MONO, size: 19, color: '7A1016', ...base }));
    else out.push(new TextRun({ text: t.slice(1, -1), italics: true, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

const body = [];
const H1 = (t) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun(t)] }));
const H2 = (t) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] }));
const H3 = (t) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(t)] }));
const P = (t) => body.push(new Paragraph({ children: runs(t) }));
const LEAD = (t) => body.push(new Paragraph({ style: 'Lead', children: runs(t) }));
const UL = (items) => items.forEach((t) => body.push(new Paragraph({ numbering: { reference: 'bullets', level: 0 }, children: runs(t) })));
let listInstance = 0;
const OL = (items) => {
  listInstance += 1;
  items.forEach((t) => body.push(new Paragraph({ numbering: { reference: 'steps', level: 0, instance: listInstance }, children: runs(t) })));
};
const NOTE = (kind, title, text) => {
  const style = { info: 'NotaInfo', warn: 'NotaAttenzione', tip: 'NotaSuggerimento' }[kind];
  body.push(new Paragraph({ style, children: [new TextRun({ text: title + '  ', bold: true }), ...runs(text)] }));
};
const CODE = (lines) => lines.forEach((l) => body.push(new Paragraph({ style: 'Codice', children: [new TextRun(l)] })));

function cell(text, width, { header = false, shade } = {}) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: header ? { type: ShadingType.CLEAR, fill: RED, color: 'auto' } : shade ? { type: ShadingType.CLEAR, fill: shade, color: 'auto' } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    verticalAlign: VerticalAlign.TOP,
    children: String(text).split('\n').map((line) => new Paragraph({
      style: 'Tabella',
      children: header ? [new TextRun({ text: line, bold: true, color: 'FFFFFF' })] : runs(line),
    })),
  });
}

function TABLE(headers, rows, ratios) {
  const total = ratios.reduce((a, b) => a + b, 0);
  const widths = ratios.map((r) => Math.floor((r / total) * CONTENT_W));
  widths[widths.length - 1] += CONTENT_W - widths.reduce((a, b) => a + b, 0);
  const border = { style: BorderStyle.SINGLE, size: 4, color: 'D5CCCC' };
  body.push(new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    layout: TableLayoutType.FIXED,
    borders: { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border },
    rows: [
      ...(headers ? [new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, widths[i], { header: true })) })] : []),
      ...rows.map((r, ri) => new TableRow({ cantSplit: true, children: r.map((c, i) => cell(i === 0 && !headers ? `**${c}**` : c, widths[i], { shade: !headers && i === 0 ? 'F4E4E4' : ri % 2 ? LIGHT : undefined })) })),
    ],
  }));
  body.push(new Paragraph({ style: 'DopoTabella', children: [] }));
}

// ------------------------------------------------------------------ copertina
const cover = [
  new Paragraph({ spacing: { before: 2600 }, children: [new TextRun({ text: 'SCARLET', font: FONT, size: 96, bold: true, color: RED, characterSpacing: 40 })] }),
  new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 18, color: RED, space: 8 } }, spacing: { after: 240 }, children: [new TextRun({ text: 'Secure Cluster Administration, Runtime & Lifecycle Engineering Tool', size: 28, color: GREY })] }),
  new Paragraph({ spacing: { before: 600 }, children: [new TextRun({ text: 'Guida utente', size: 64, bold: true, color: DARK })] }),
  new Paragraph({ spacing: { before: 120 }, children: [new TextRun({ text: 'Console operativa per Kubernetes e Podman', size: 32, color: GREY })] }),
  new Paragraph({ spacing: { before: 1800 }, children: [new TextRun({ text: 'Da leggere prima di usare il sistema.', size: 26, italics: true, color: DARK })] }),
  new Paragraph({ spacing: { before: 120 }, children: [new TextRun({ text: 'Spiega cos’è Scarlet, come ragiona, cosa si può fare in sicurezza e cosa richiede attenzione: chi la legge per intero arriva al primo accesso sapendo già dove guardare e come comportarsi.', size: 24, color: GREY })] }),
  new Paragraph({ spacing: { before: 1400 }, children: [new TextRun({ text: `Versione del sistema: ${VERSION}`, size: 24, color: DARK })] }),
  new Paragraph({ children: [new TextRun({ text: 'Edizione: ottobre 2026', size: 24, color: DARK })] }),
  new Paragraph({ children: [new TextRun({ text: 'Lingua dell’interfaccia descritta: italiano (disponibile anche in inglese)', size: 24, color: DARK })] }),
];

const toc = [
  new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun('Indice')] }),
  new TableOfContents('Indice', { hyperlink: true, headingStyleRange: '1-2' }),
  new Paragraph({ style: 'Nota', children: [new TextRun({ text: 'Se l’indice appare vuoto, in Word fare clic con il tasto destro sull’indice e scegliere “Aggiorna campo”.', italics: true, color: GREY, size: 18 })] }),
];

// ==================================================================== CONTENUTO
H1('1. Informazioni su questo documento');
LEAD('Questa guida accompagna chi userà Scarlet nel lavoro di tutti i giorni: operatori, sistemisti, amministratori e chiunque debba controllare o intervenire sulle applicazioni ospitate in Kubernetes e Podman. È pensata per essere letta prima di accedere al sistema.');
H2('1.1 Scopo');
P('Il documento spiega:');
UL([
  'che cos’è Scarlet e quale problema risolve;',
  'i concetti di Kubernetes e Podman indispensabili per capire ciò che si vede a schermo, spiegati in linguaggio semplice;',
  'come è organizzata l’interfaccia e dove trovare ogni informazione;',
  'come leggere lo stato del sistema, riconoscere un problema e decidere cosa fare;',
  'quali operazioni modificano il sistema, quali rischi comportano e quali protezioni offre Scarlet;',
  'ruoli, permessi, tracciabilità (audit) e backup.',
]);
P('Non è un manuale di installazione: installazione, aggiornamento e manutenzione del server sono descritti nei documenti tecnici `INSTALL.md`, `OPERATIONS.md`, `BACKUP.md` e `SECURITY.md` forniti con il prodotto.');
H2('1.2 A chi è rivolto');
TABLE(['Profilo', 'Cosa leggere con più attenzione'], [
  ['Operatore junior, nuovo a Kubernetes', 'Capitoli 2, 3, 5, 6, 7 e 9: concetti, interfaccia, dashboard, Centro Operativo e diagnosi dei problemi comuni.'],
  ['Sistemista / operatore esperto', 'Capitoli 8, 10, 11, 12 e 14: risorse, pubblicazione di applicazioni, operazioni, manutenzione e monitoraggio.'],
  ['Amministratore della piattaforma', 'Tutto il documento, in particolare i capitoli 4, 16, 17 e 18: ruoli, sicurezza, backup e impostazioni.'],
  ['Utente in sola lettura (Viewer)', 'Capitoli 2, 3, 5, 6, 7 e 15: per consultare lo stato del sistema senza modificarlo.'],
], [3, 7]);
H2('1.3 Convenzioni');
UL([
  'Le voci di menu, i pulsanti e le schede sono in **grassetto**, ad esempio **Operazioni → Deploy**.',
  'Nomi di risorse, valori da digitare, percorsi e comandi sono in `carattere monospazio`.',
  'I riquadri evidenziati richiamano l’attenzione su tre tipi di informazione:',
]);
NOTE('info', 'Nota.', 'informazioni utili per capire meglio.');
NOTE('tip', 'Suggerimento.', 'un modo più semplice o più sicuro di fare qualcosa.');
NOTE('warn', 'Attenzione.', 'operazioni che possono interrompere un servizio o perdere dati.');
H2('1.4 Versione descritta');
P(`La guida descrive **Scarlet ${VERSION}**. Il numero di versione in uso è sempre visibile nell’intestazione dell’applicazione (in alto a destra, insieme alle versioni di Kubernetes, di Podman e dell’API) e nel piè di pagina di questo documento.`);

// ------------------------------------------------------------------
H1('2. Scarlet in sintesi');
LEAD('Scarlet è una console web che rende Kubernetes e Podman comprensibili e governabili anche da chi non li conosce a fondo. Non è una semplice dashboard: è un centro operativo che risponde subito alle domande che contano quando qualcosa non va.');
H2('2.1 Le domande a cui risponde');
UL([
  '**Ci sono problemi?** La dashboard e il Centro Operativo li mostrano appena vengono rilevati.',
  '**Quali e quanto sono gravi?** Ogni problema ha una gravità: CRITICAL, ERROR, WARNING o INFO.',
  '**Chi è coinvolto?** Applicazione, Pod, nodo e namespace interessati sono indicati esplicitamente.',
  '**Perché succede?** Scarlet esegue controlli sui dati reali e indica la causa più probabile.',
  '**Cosa posso fare e con quale rischio?** Le azioni possibili sono proposte accanto al problema e, prima di eseguirle, Scarlet ne spiega conseguenze e rischio.',
]);
H2('2.2 Il metodo: capire prima di agire');
P('Tutta l’applicazione è costruita attorno a un metodo in cinque passi, che conviene adottare anche come abitudine personale:');
OL([
  '**Capire** – leggere la spiegazione in linguaggio semplice di ciò che si vede.',
  '**Diagnosticare** – consultare controlli, eventi e log per trovare la causa.',
  '**Decidere** – scegliere l’intervento valutando conseguenze e rischio, mostrati da Scarlet.',
  '**Agire** – eseguire l’operazione dall’interfaccia, con le conferme previste.',
  '**Verificare** – controllare che il problema sia risolto e che non ne siano nati altri.',
]);
P('L’alternativa da evitare è il ciclo “clicco, spero, errore”. Scarlet aiuta a evitarlo spiegando ogni concetto e ogni azione e collegando ogni pagina all’articolo pertinente della guida integrata.');
H2('2.3 Cosa gestisce');
TABLE(['Area', 'Cosa si può fare'], [
  ['Kubernetes', 'Consultare cluster, nodi, namespace, applicazioni (Pod, Deployment, StatefulSet, DaemonSet, Job, CronJob), rete (Service, Ingress, Endpoints), storage (PV, PVC, StorageClass), configurazione (ConfigMap, Secret) ed eventi. Pubblicare nuove applicazioni, scalarle, riavviarle, aggiornarle e riportarle a una versione precedente.'],
  ['Podman', 'Vedere e gestire i container e le immagini Podman dell’host su cui è installato Scarlet: avvio, arresto, riavvio, log, scaricamento ed eliminazione delle immagini.'],
  ['Diagnostica', 'Rilevamento automatico dei problemi più comuni, con spiegazione, controlli eseguiti, causa probabile e azioni suggerite.'],
  ['Monitoraggio', 'Uso di CPU e memoria, storage, stato di salute dei componenti, alta affidabilità, eventi e log dei container.'],
  ['Governo', 'Utenti e ruoli, audit di tutte le operazioni significative, backup dell’applicazione, impostazioni.'],
], [2, 8]);
H2('2.4 Cosa Scarlet non fa');
UL([
  'Non sostituisce il backup del cluster: il backup di Scarlet salva la configurazione e lo stato di Scarlet stesso, non i dati delle applicazioni né lo stato di Kubernetes (vedere il capitolo 17).',
  'Non inventa dati: se una metrica non è disponibile, lo dice esplicitamente (“Metriche avanzate non configurate”).',
  'Non entra nei container e non esegue comandi al loro interno: questa possibilità non è prevista per scelta di sicurezza.',
  'Non gestisce altri cluster oltre a quello configurato.',
]);
H2('2.5 LIVE o DEMO: su cosa sto lavorando?');
P('Scarlet può funzionare in due modalità, sempre ben distinguibili:');
TABLE(['Modalità', 'Come si riconosce', 'Uso'], [
  ['**LIVE**', 'Etichetta verde “● LIVE · <contesto>” nell’intestazione, con il nome del cluster collegato.', 'Ambiente reale: ogni operazione agisce sul cluster vero.'],
  ['**DEMO**', 'Banda viola a strisce in cima a ogni pagina con la scritta “MODALITÀ DEMO — dati simulati” ed etichetta “DEMO”.', 'Formazione e prove: i dati sono simulati, nessun cluster reale è coinvolto.'],
], [1.4, 4.3, 4.3]);
NOTE('warn', 'Attenzione.', 'prima di qualunque operazione controllare sempre l’etichetta in alto. Se compare “Kubernetes non connesso”, Scarlet non riesce a comunicare con il cluster: i dati mostrati potrebbero non essere aggiornati e le operazioni falliranno.');
NOTE('info', 'Nota.', 'la modalità DEMO non può essere attivata su un’installazione di produzione: è un vincolo tecnico, non una semplice convenzione.');

// ------------------------------------------------------------------
H1('3. Concetti di base prima di iniziare');
LEAD('Non serve essere esperti di Kubernetes per usare Scarlet, ma alcuni concetti ricorrono in ogni pagina. Questo capitolo li presenta nel modo più semplice possibile; la guida integrata (menu **Guida**) li approfondisce con dettagli tecnici, esempi e casi di errore.');
H2('3.1 Kubernetes in poche parole');
P('**Kubernetes** è un sistema che esegue applicazioni confezionate in container su un insieme di macchine e si occupa di tenerle in funzione: se un’applicazione si ferma la riavvia, se una macchina si guasta sposta il lavoro altrove, se serve più capacità aggiunge copie. Si dice a Kubernetes *come deve essere* il sistema (quante copie, quale versione, quante risorse) e lui lavora continuamente per mantenerlo così.');
H2('3.2 I mattoni fondamentali');
TABLE(['Concetto', 'In parole semplici', 'Dove lo trovo in Scarlet'], [
  ['Cluster', 'L’insieme delle macchine gestite da Kubernetes, viste come un unico sistema.', 'Cluster → Panoramica'],
  ['Nodo (Node)', 'Una delle macchine del cluster, fisica o virtuale, che esegue le applicazioni.', 'Cluster → Nodi'],
  ['Namespace', 'Una “cartella” che separa applicazioni e ambienti, ad esempio produzione e collaudo.', 'Cluster → Namespace; filtro in ogni elenco'],
  ['Container', 'Un’applicazione confezionata con tutto ciò che le serve per funzionare.', 'Dettaglio di un Pod; Container (Podman)'],
  ['Immagine', 'Il “pacchetto” da cui nasce un container, scaricato da un registry.', 'Operazioni → Onboarding immagine; Container → Immagini'],
  ['Pod', 'La più piccola unità eseguita: uno o più container che girano insieme.', 'Applicazioni → Pod'],
  ['Deployment', 'Gestisce una o più copie di un’applicazione e permette di aggiornarle progressivamente.', 'Applicazioni → Deployments'],
  ['ReplicaSet', 'Mantiene il numero di copie richiesto per una versione di un Deployment.', 'Scheda Relazioni di un Deployment'],
  ['StatefulSet', 'Come un Deployment, ma per applicazioni con dati (database): ogni copia ha nome e disco propri.', 'Applicazioni → StatefulSets'],
  ['DaemonSet', 'Esegue una copia su ogni nodo: tipico per agenti di monitoraggio e log.', 'Applicazioni → DaemonSets'],
  ['Job / CronJob', 'Un’attività che deve completarsi (Job), eventualmente pianificata a orari fissi (CronJob).', 'Applicazioni → Jobs / CronJobs'],
  ['Service', 'Un nome e un indirizzo stabili per raggiungere le copie pronte di un’applicazione.', 'Networking → Services'],
  ['Ingress', 'Rende un’applicazione web raggiungibile dall’esterno con un nome host.', 'Networking → Ingress'],
  ['ConfigMap / Secret', 'Configurazione dell’applicazione separata dall’immagine; i Secret contengono dati riservati.', 'Configurazione → ConfigMaps / Secrets'],
  ['PV / PVC / StorageClass', 'Disco persistente (PV), richiesta di disco da parte di un’applicazione (PVC), tipo di storage disponibile (StorageClass).', 'Storage'],
  ['Evento', 'Un messaggio di Kubernetes su ciò che succede a una risorsa; scade dopo circa un’ora.', 'Cluster → Eventi; scheda Eventi di ogni risorsa'],
], [2, 5, 3]);
H2('3.3 Affidabilità: repliche, aggiornamenti e controlli di salute');
UL([
  '**Replica** – una copia identica dell’applicazione. Con almeno due repliche, la perdita di un Pod o di un nodo non interrompe il servizio: Kubernetes ricrea automaticamente la copia mancante.',
  '**Rolling update** – l’aggiornamento progressivo: le nuove copie sostituiscono le vecchie una alla volta, senza fermare il servizio.',
  '**Rollback** – il ritorno a una versione precedente quando un aggiornamento crea problemi.',
  '**Readiness probe** – il controllo che dice a Kubernetes quando una copia è pronta a ricevere traffico. Senza readiness probe il traffico può arrivare a un’applicazione non ancora avviata.',
  '**Liveness probe** – il controllo che dice a Kubernetes se una copia è bloccata e va riavviata.',
  '**Request e limit** – la quantità di CPU e memoria riservata a un container (request) e quella massima che può usare (limit). Superando il limite di memoria il container viene terminato (OOMKilled).',
  '**PodDisruptionBudget** – una regola che garantisce un numero minimo di copie attive durante la manutenzione dei nodi.',
]);
H2('3.4 Podman');
P('**Podman** esegue container direttamente su un singolo server, senza un cluster. In Scarlet è gestito in una sezione separata (**Container**), con un’intestazione che dichiara sempre “Runtime: Podman”: i container Podman non sono Pod di Kubernetes e non vanno confusi con essi.');
NOTE('info', 'Nota.', 'Kubernetes e Podman possono usare le stesse immagini, ma sono gestori indipendenti. Scaricare un’immagine con Podman non la rende disponibile automaticamente ai nodi di Kubernetes.');

// ------------------------------------------------------------------
H1('4. Accesso, ruoli e sessione');
H2('4.1 Primo accesso');
OL([
  'Aprire con il browser l’indirizzo comunicato dall’amministratore (nell’installazione attuale `https://mv3412.farm.ised.it:8443`).',
  'Se il browser segnala un certificato non attendibile, l’installazione usa ancora il certificato generato automaticamente: verificare con l’amministratore prima di proseguire.',
  'Inserire nome utente e password e premere **Accedi**.',
  'Se l’amministratore ha impostato una password temporanea, Scarlet chiede subito di sceglierne una nuova: fino a quel momento le altre pagine non sono accessibili.',
]);
NOTE('info', 'Nota.', 'la primissima apertura di un’installazione nuova mostra la **Configurazione iniziale**, una procedura in 11 passi riservata a chi installa il sistema: richiede un codice monouso e crea il primo amministratore. Gli utenti normali non la vedranno mai.');
H2('4.2 Regole sulla password');
UL([
  'almeno 12 caratteri;',
  'almeno tre tipi di carattere tra minuscole, maiuscole, numeri e simboli;',
  'non deve contenere il nome utente e non deve essere una password comune.',
]);
P('Dopo **5 tentativi errati** l’account viene bloccato per **15 minuti**; un amministratore può sbloccarlo prima da **Sicurezza → Utenti**. Una password dimenticata può essere reimpostata solo da un amministratore: Scarlet conserva le password esclusivamente in forma cifrata non reversibile e nessuno può leggerle.');
H2('4.3 Durata della sessione');
P('La sessione scade dopo **30 minuti di inattività** e comunque dopo **12 ore** dall’accesso. In **Profilo** si vedono le sessioni aperte e si possono chiudere tutte le altre, ad esempio dopo aver usato un PC condiviso. Il cambio della password chiude automaticamente tutte le sessioni.');
H2('4.4 Ruoli');
P('Ogni utente ha uno dei tre ruoli seguenti. I permessi sono verificati dal server, non solo nascondendo i pulsanti: un’operazione non consentita viene rifiutata e registrata nell’audit.');
TABLE(['Capacità', 'Viewer', 'Operator', 'Administrator'], [
  ['Consultare dashboard, risorse, eventi, metriche, Podman', '✓', '✓', '✓'],
  ['Leggere e scaricare i log dei container', '—', '✓', '✓'],
  ['Pubblicare applicazioni (wizard, YAML dei workload)', '—', '✓', '✓'],
  ['Scalare, riavviare, rollout e rollback', '—', '✓', '✓'],
  ['Eliminare (ricreare) un Pod', '—', '✓', '✓'],
  ['Avviare / fermare / riavviare container Podman', '—', '✓', '✓'],
  ['Segnare i problemi come gestiti', '—', '✓', '✓'],
  ['Eliminare altre risorse (Deployment, PVC, Namespace…)', '—', '—', '✓'],
  ['Applicare YAML di qualsiasi tipo, creare namespace', '—', '—', '✓'],
  ['Vedere il contenuto dei Secret (registrato nell’audit)', '—', '—', '✓'],
  ['Manutenzione dei nodi (cordon, drain)', '—', '—', '✓'],
  ['Eliminare container, scaricare/eliminare immagini Podman', '—', '—', '✓'],
  ['Utenti, audit log, impostazioni, backup, manutenzione', '—', '—', '✓'],
], [5.2, 1.6, 1.6, 1.6]);
H2('4.5 Lingua e tema');
P('La lingua (italiano o inglese) si cambia dal selettore nell’intestazione o da **Profilo**, dove la scelta viene memorizzata per l’utente. Il pulsante con il sole/la luna alterna tema chiaro, scuro e quello del sistema operativo.');

// ------------------------------------------------------------------
H1('5. L’interfaccia');
H2('5.1 Struttura della pagina');
TABLE(['Zona', 'Contenuto'], [
  ['Banda superiore', 'Solo in modalità DEMO: banda viola a strisce che segnala i dati simulati.'],
  ['Intestazione', 'Campo di ricerca globale (Ctrl+K), etichetta LIVE/DEMO con il contesto del cluster, versioni di Kubernetes, Podman, Scarlet e API, campanella delle notifiche con il numero di problemi aperti, tema, lingua, utente con il ruolo, uscita.'],
  ['Menu laterale', 'Tutte le sezioni, organizzate in gruppi espandibili.'],
  ['Area principale', 'Titolo della pagina con la spiegazione in linguaggio semplice, collegamento alla guida (“Cos’è …?”), contenuto e azioni.'],
  ['Piè di pagina', 'A sinistra il copyright, a destra il nome e la versione di Scarlet in uso (passandoci sopra il mouse compare la versione dell’API).'],
], [2, 8]);
H2('5.2 Il menu laterale');
P('I gruppi si aprono e si chiudono con un clic; Scarlet ricorda quali gruppi sono aperti. Il pulsante **Riduci il menu** in basso lascia solo le icone per avere più spazio; su schermi piccoli il menu diventa un pannello a scomparsa.');
TABLE(['Gruppo', 'Voci'], [
  ['Dashboard', 'Riepilogo dello stato del cluster.'],
  ['Centro Operativo', 'Tutti i problemi rilevati, dal più grave.'],
  ['Cluster', 'Panoramica, Nodi, Namespace, Eventi.'],
  ['Applicazioni', 'Pod, Deployments, StatefulSets, DaemonSets, Jobs, CronJobs.'],
  ['Networking', 'Services, Ingress, Endpoints.'],
  ['Storage', 'Persistent Volumes, Persistent Volume Claims, Storage Classes.'],
  ['Configurazione', 'ConfigMaps, Secrets.'],
  ['Container', 'Container, Immagini, Registry (Podman).'],
  ['Monitoraggio', 'CPU, Memoria, Storage, Health, Alta affidabilità, Eventi, Log.'],
  ['Operazioni', 'Onboarding immagine, Deploy, Scale, Restart, Rollout, Applica YAML, Backup, Manutenzione.'],
  ['Sicurezza', 'Utenti, Ruoli, Permessi, Audit Log.'],
  ['Guida', 'Guida integrata, ricercabile.'],
  ['Impostazioni', 'Sistema, Kubernetes, Podman, Logging, Backup, Autenticazione.'],
], [2.2, 7.8]);
NOTE('info', 'Nota.', 'le voci per cui il proprio ruolo non ha permessi non compaiono nel menu.');
H2('5.3 Colori e stati');
P('Lo stato di ogni risorsa è indicato da un’etichetta colorata con un nome esplicito, così da non dipendere solo dal colore:');
TABLE(['Etichetta', 'Colore', 'Significato'], [
  ['Integro', 'verde', 'Funziona come previsto.'],
  ['Completato', 'verde', 'Attività terminata con successo (Job, Pod di un Job).'],
  ['In aggiornamento', 'blu', 'Sta cambiando, ad esempio durante un rolling update.'],
  ['In attesa', 'giallo', 'Non ancora avviato: in attesa di un nodo, di un volume o di un’immagine.'],
  ['Degradato', 'giallo', 'Funziona parzialmente: alcune copie non sono pronte.'],
  ['In errore', 'rosso', 'Non funziona: va diagnosticato.'],
  ['Sospeso', 'grigio', 'Fermato volontariamente (repliche a zero, CronJob sospeso, rollout in pausa).'],
  ['Sconosciuto', 'grigio', 'Lo stato non è determinabile (ad esempio nodo irraggiungibile).'],
], [2, 1.5, 6.5]);
H2('5.4 Messaggi di errore');
P('Quando un’operazione non riesce, Scarlet non mostra codici incomprensibili: spiega cosa è successo, la causa probabile e cosa fare, con pulsanti come **Riprova** o **Verifica connessione Kubernetes**. Il dettaglio tecnico originale resta disponibile nella sezione richiudibile **Dettagli tecnici**, utile da copiare quando si chiede supporto (contiene anche un identificativo della richiesta che permette di trovarla nei log del server).');

// ------------------------------------------------------------------
H1('6. La Dashboard');
LEAD('La dashboard è la prima pagina dopo l’accesso. In pochi secondi dice se il cluster è in salute e dove guardare. Ogni riquadro è cliccabile e porta al dettaglio.');
TABLE(['Riquadro', 'Cosa indica', 'Quando preoccuparsi'], [
  ['Stato cluster', 'Sintesi: Integro, Da verificare, Errori, Critico o Non raggiungibile, con il numero di problemi per gravità.', 'Critico o Errori: aprire il Centro Operativo.'],
  ['Nodi disponibili', 'Nodi pronti sul totale; segnala quelli non disponibili o in manutenzione.', 'Qualunque nodo non disponibile.'],
  ['Pod attivi', 'Pod in esecuzione, con totali, in attesa e completati.', 'Molti Pod in attesa per lungo tempo.'],
  ['Pod in errore', 'Pod che non funzionano.', 'Valore maggiore di zero.'],
  ['Deployment / degradati', 'Applicazioni totali e quelle non disponibili o parziali.', 'Qualunque Deployment non disponibile.'],
  ['Eventi di warning', 'Avvisi di Kubernetes nell’ultima ora circa.', 'Crescita improvvisa.'],
  ['Restart container', 'Riavvii totali dei container attivi.', 'Aumento continuo: segno di instabilità.'],
  ['CPU e memoria', 'Uso reale (da metrics-server) e quantità richiesta dai Pod rispetto a quella allocabile.', 'Uso o richieste sopra l’80–90%.'],
  ['Storage', 'Volumi persistenti, capacità, richieste di volume collegate e in attesa.', 'PVC in attesa (pending).'],
  ['Pod con più restart / Problemi recenti / Eventi', 'Elenchi brevi dei casi più rilevanti.', 'Da usare come punto di partenza della diagnosi.'],
], [2.2, 4.6, 3.2]);
NOTE('tip', 'Suggerimento.', 'la dashboard si aggiorna automaticamente; il pulsante **Aggiorna** forza la lettura immediata. In basso è ricordato il significato delle quattro gravità.');

// ------------------------------------------------------------------
H1('7. Centro Operativo e notifiche');
LEAD('Il Centro Operativo raccoglie tutti i problemi che Scarlet rileva automaticamente, ordinati dal più grave. È la pagina da cui partire quando qualcosa non funziona.');
H2('7.1 Gravità');
TABLE(['Gravità', 'Significato', 'Reazione attesa'], [
  ['CRITICAL', 'Servizio probabilmente non disponibile (es. applicazione con 0 repliche pronte, nodo non pronto).', 'Intervenire subito.'],
  ['ERROR', 'Malfunzionamento in corso (es. container che si riavvia di continuo).', 'Intervenire a breve.'],
  ['WARNING', 'Situazione anomala da verificare (es. Pod in attesa, applicazione parzialmente degradata).', 'Verificare e pianificare.'],
  ['INFO', 'Informazione (es. rollout in pausa, nodo in manutenzione).', 'Nessuna azione obbligatoria.'],
], [1.5, 5.5, 3]);
H2('7.2 Come leggere una scheda problema');
P('Ogni problema è presentato in una scheda con sempre la stessa struttura:');
OL([
  '**Intestazione** – gravità, nome del problema (es. `CrashLoopBackOff`), applicazione o risorsa coinvolta, namespace e da quanto tempo dura.',
  '**Cosa sta succedendo** – spiegazione in linguaggio semplice, per esempio: “Il container si avvia e si chiude subito con un errore”.',
  '**Rischio** – le conseguenze per il servizio.',
  '**Controlli eseguiti** – verifiche fatte da Scarlet sui dati reali, ciascuna con esito OK, Problema, Attenzione o Non verificabile. Il controllo più indicativo è marcato come **Causa più probabile**.',
  '**Dati** – applicazione, Pod coinvolti, nodo, container, immagine, numero di riavvii; il messaggio originale di Kubernetes è nella sezione **Messaggio di Kubernetes**.',
  '**Azioni** – pulsanti pertinenti: Visualizza problema, Visualizza eventi, Visualizza log, Log dell’esecuzione precedente, Visualizza YAML, Riavvia, Rollback, Verifica registry, **Come risolvere** (apre l’articolo della guida).',
]);
NOTE('info', 'Nota.', 'quando più Pod della stessa applicazione hanno lo stesso problema, Scarlet li raggruppa in un’unica scheda indicando quanti sono: si vede un problema, non dieci copie dello stesso.');
H2('7.3 Segnare un problema come gestito');
P('Chi prende in carico un problema può premere **Segna come gestito**: gli altri vedranno “Gestito da <utente>” e l’opzione **Nascondi quelli già gestiti** permette di concentrarsi sul resto. Quando il problema scompare, Scarlet lo segna automaticamente come **risolto**; se si ripresenta, torna **aperto**.');
H2('7.4 Notifiche');
P('La campanella nell’intestazione mostra il numero di problemi aperti e apre un pannello con le notifiche, filtrabili per stato (attive, aperte, gestite, risolte), gravità e testo. Le notifiche si aggiornano da sole quando il server rileva una variazione; il pulsante **Ricontrolla** forza una nuova verifica.');

// ------------------------------------------------------------------
H1('8. Le risorse Kubernetes');
H2('8.1 Gli elenchi');
P('Ogni voce dei gruppi Cluster, Applicazioni, Networking, Storage e Configurazione apre l’elenco delle risorse di quel tipo. In cima alla pagina c’è la spiegazione di cosa sia quel tipo di risorsa e il collegamento “Cos’è …?” alla guida.');
UL([
  '**Filtro di testo** – cerca in tutte le colonne.',
  '**Namespace** – limita l’elenco a un namespace.',
  '**Stato** – mostra solo le risorse integre, in errore, in attesa… oppure **Solo con problemi**.',
  '**Ordinamento** – clic sull’intestazione di colonna.',
  '**Azioni rapide** – per Deployment e StatefulSet: Scala e Riavvia; per i Pod: Riavvia e Log.',
  '**Crea** – pulsante in alto a destra (es. **Crea Job**, **Crea Secret**): apre un modello pronto per quel tipo di risorsa (paragrafo 11.5).',
]);
H2('8.2 La pagina di dettaglio');
P('Un clic su una riga apre il dettaglio della risorsa. Se Scarlet ha rilevato un problema su di essa, compare un riquadro colorato in alto con un collegamento alla diagnostica. Il contenuto è organizzato in schede:');
TABLE(['Scheda', 'Contenuto'], [
  ['Panoramica', 'Vista semplice: stato, proprietà principali, una frase che riassume la situazione (es. “Questa applicazione ha 3 repliche desiderate e 3 pronte”), container con risorse e probe, condizioni di Kubernetes, label.'],
  ['Relazioni', 'Schema di come la risorsa è collegata alle altre, da sinistra a destra: Accesso (Ingress, Service) → Applicazione → Versione (ReplicaSet) → Pod → Risorse usate (nodo, volumi, ConfigMap, Secret). Ogni elemento è cliccabile.'],
  ['Pod', 'Per applicazioni e nodi: i Pod che ne fanno parte.'],
  ['Eventi', 'Gli eventi recenti di Kubernetes su questa risorsa.'],
  ['Log', 'Per i Pod: il visualizzatore dei log (capitolo 14.7).'],
  ['Metriche', 'Uso di CPU e memoria rispetto ai limiti, quando metrics-server è disponibile.'],
  ['YAML', 'La definizione completa della risorsa, in YAML o JSON, con modifica controllata (paragrafo 8.4).'],
  ['Diagnostica', 'Le schede problema relative a questa risorsa.'],
], [1.8, 8.2]);
P('In alto a destra ci sono le azioni disponibili per quel tipo di risorsa e per il proprio ruolo (Scala, Riavvia, Pausa/Riprendi, Rollout, Sospendi, Esegui ora, Cordon, Drain, Elimina).');
H2('8.3 I Secret');
P('I valori dei Secret sono sempre nascosti (••••••••). Solo un amministratore può premere **Mostra i valori**: l’accesso viene registrato nell’audit log con nome utente e orario. Anche la vista YAML nasconde i valori.');
H2('8.4 Modificare lo YAML in sicurezza');
P('Lo YAML è la descrizione testuale completa di una risorsa. Scarlet non lo nasconde, ma lo protegge:');
OL([
  'Nella scheda **YAML** premere **Modifica**: l’editor evidenzia la sintassi e segnala subito gli errori di formato con il numero di riga.',
  'Premere **Valida**: Scarlet chiede a Kubernetes di provare la modifica senza applicarla (dry-run) e mostra eventuali errori sui campi.',
  'Premere **Differenze** per confrontare la versione attuale con quella modificata.',
  'Premere **Applica**: una finestra riassume l’operazione con le differenze; solo dopo la conferma la modifica viene inviata.',
]);
NOTE('warn', 'Attenzione.', 'modificare il template di un Deployment, StatefulSet o DaemonSet avvia un aggiornamento progressivo di tutti i suoi Pod.');

// ------------------------------------------------------------------
H1('9. Diagnosticare i problemi più comuni');
LEAD('Questo capitolo descrive i problemi che Scarlet rileva più spesso: cosa si vede, cosa significa, quali controlli guardare e come intervenire. Per ciascuno, il pulsante “Come risolvere” della scheda apre l’articolo completo della guida.');
const problem = (name, see, means, check, act) => {
  H2(name);
  TABLE(null, [['Cosa si vede', see], ['Cosa significa', means], ['Cosa controllare', check], ['Cosa fare', act]], [2, 8]);
};
problem('9.1 CrashLoopBackOff', 'Pod in errore con stato `CrashLoopBackOff`, riavvii in crescita.', 'Il container si avvia e termina subito; Kubernetes continua a riavviarlo aspettando sempre più a lungo tra un tentativo e l’altro.', 'Controllo **Codice di uscita** (1 = errore dell’applicazione, 127 = comando non trovato, 137 = terminato per memoria…); **Liveness probe**; **Memoria**. Aprire **Log dell’esecuzione precedente**: lì c’è l’errore che ha fatto terminare il container.', 'Correggere la causa letta nei log (configurazione, dipendenza irraggiungibile, comando errato). Un riavvio da solo non risolve un errore di configurazione. Se il problema è nato con un aggiornamento: **Rollback**.');
problem('9.2 ImagePullBackOff / ErrImagePull', 'Pod in attesa con stato `ImagePullBackOff` o `ErrImagePull`.', 'Kubernetes non riesce a scaricare l’immagine del container.', 'Controlli **Nome immagine**, **Esistenza dell’immagine/tag**, **Registry**, **Autenticazione**: la causa più probabile è evidenziata (tag inesistente, registry irraggiungibile, credenziali mancanti).', 'Usare **Verifica registry**: apre il wizard di onboarding con l’immagine già inserita e verifica sul registry se esiste e se servono credenziali. Correggere il tag o il nome; per registry privati serve un Secret di tipo registry (imagePullSecrets).');
problem('9.3 OOMKilled', 'Container riavviato con ultima terminazione `OOMKilled`.', 'Il container ha superato il limite di memoria ed è stato terminato.', 'Controlli **Limite di memoria** e **Uso di memoria attuale**; scheda **Metriche**.', 'Aumentare il limite di memoria (YAML o nuovo deploy) se il carico è legittimo; se la memoria cresce senza fermarsi c’è probabilmente un difetto dell’applicazione da segnalare.');
problem('9.4 Pending', 'Pod in attesa da tempo, senza nodo assegnato.', 'Kubernetes non trova un nodo dove eseguire il Pod.', 'Controlli **Nodi disponibili**, **Capacità CPU/memoria**, **Taint**, **Selettori di nodo**, **Volumi**.', 'Ridurre le risorse richieste, liberare capacità, aggiungere nodi o correggere selettori e volumi. Un PVC in attesa blocca anche i Pod che lo usano.');
problem('9.5 Nodo NotReady', 'Nodo non pronto, gravità CRITICAL.', 'Il nodo non comunica più con il cluster; dopo alcuni minuti Kubernetes sposta altrove i suoi Pod.', 'Controlli **Heartbeat del kubelet** e **Condizioni del nodo** (disco, memoria, processi).', 'Coinvolgere l’amministratore di sistema: verificare che la macchina sia accesa, raggiungibile e che il servizio Kubernetes del nodo sia attivo.');
problem('9.6 CreateContainerConfigError', 'Container che non parte con errore di configurazione.', 'Manca un ConfigMap, un Secret o una chiave a cui il container fa riferimento.', 'Controlli **ConfigMap referenziati**, **Secret referenziati**, **Chiavi**: sono elencati gli elementi mancanti.', 'Creare l’elemento mancante o correggere il riferimento nel Deployment.');
problem('9.7 Pod Failed / Unknown', 'Pod terminato con errore o in stato sconosciuto.', 'Failed: il Pod ha terminato il lavoro con un errore. Unknown: il nodo che lo esegue non risponde.', 'Controllo **Stato del nodo**; log del Pod.', 'Per Unknown seguire la procedura del nodo non pronto; per Failed leggere i log e correggere la causa.');
problem('9.8 Applicazione non disponibile o degradata', 'Deployment con 0 repliche pronte (CRITICAL) o con solo una parte pronta.', 'Il servizio è fermo o ha capacità ridotta.', 'Le schede problema dei Pod della stessa applicazione indicano quasi sempre la causa reale.', 'Intervenire sulla causa dei Pod; se il problema è iniziato con un aggiornamento, valutare il **Rollback**.');
problem('9.9 PVC in attesa', 'Richiesta di volume in stato Pending.', 'Lo spazio disco richiesto non è ancora stato assegnato.', 'Controlli **StorageClass**, **Binding**, **Provisioning**.', 'Se la StorageClass crea il volume solo quando un Pod lo usa, l’attesa è normale. Altrimenti correggere la StorageClass indicata.');

// ------------------------------------------------------------------
H1('10. Pubblicare un’applicazione');
LEAD('Scarlet permette di pubblicare un’applicazione senza scrivere YAML, con due procedure guidate in sequenza: l’onboarding dell’immagine e il deploy. Prima di applicare qualsiasi cosa mostra il riepilogo, i rischi, la validazione sul cluster e lo YAML generato.');
H2('10.1 Onboarding immagine');
P('**Operazioni → Onboarding immagine** verifica un’immagine prima di usarla. È il punto di partenza consigliato per ogni nuova applicazione.');
TABLE(['Passo', 'Cosa succede'], [
  ['1. Sorgente', 'Si indica il riferimento dell’immagine (es. `registry.example.com/team/app:1.4.2`) oppure si sceglie un’immagine già presente in Podman. Per registry privati si possono inserire credenziali: usate una sola volta, mai salvate.'],
  ['2. Verifica', 'Scarlet interroga il registry: nome valido, registry raggiungibile, autenticazione, esistenza del tag, disponibilità per l’architettura del server. Ogni esito negativo è spiegato con cosa fare.'],
  ['3. Analisi', 'Legge le caratteristiche dell’immagine: porte esposte, utente con cui gira, variabili d’ambiente (quelle sensibili nascoste), comando di avvio, volumi dichiarati, dimensione. Segnala i rischi: tag “latest”, esecuzione come root, nessuna porta, segreti nell’immagine.'],
  ['4. Destinazione', 'Propone nome dell’applicazione, namespace, numero di repliche, porta, storage e controlli di salute coerenti con l’immagine.'],
  ['5. Riepilogo', 'Pulsante **Continua nel wizard di deploy**: i valori passano già compilati alla procedura di deploy.'],
], [2, 8]);
H2('10.2 Wizard di deploy');
P('**Operazioni → Deploy** guida in 12 passi; si può tornare ai passi già completati in qualsiasi momento.');
TABLE(['Passo', 'Cosa chiede', 'Consiglio'], [
  ['1. Nome', 'Nome dell’applicazione e namespace (eventualmente da creare, solo amministratori).', 'Lettere minuscole, numeri e trattini.'],
  ['2. Container image', 'Immagine senza tag.', 'Verificarla prima con l’onboarding.'],
  ['3. Tag', 'Versione dell’immagine.', 'Usare una versione precisa, mai `latest`.'],
  ['4. Repliche', 'Numero di copie.', 'Almeno 2 per i servizi importanti.'],
  ['5. Porta', 'Porta su cui l’applicazione ascolta.', 'Quella indicata dall’analisi dell’immagine.'],
  ['6. CPU', 'Request e limit di CPU.', 'Request realistiche permettono a Kubernetes di distribuire bene il carico.'],
  ['7. RAM', 'Request e limit di memoria.', 'Impostare sempre il limite di memoria.'],
  ['8. Storage', 'Disco persistente: dimensione, StorageClass, percorso di montaggio, modalità di accesso.', 'Un disco ReadWriteOnce con più repliche è un rischio segnalato.'],
  ['9. Networking', 'Service (interno, NodePort, LoadBalancer) e Ingress con host e certificato.', 'Esporre all’esterno solo ciò che serve, con TLS.'],
  ['10. Health check', 'Readiness e liveness probe (HTTP o TCP).', 'Senza readiness il traffico arriva anche a copie non pronte.'],
  ['11. Riepilogo', 'Sintesi in linguaggio semplice, rischi, eventuali blocchi, risultato della validazione sul cluster (dry-run) e YAML generato, scaricabile.', 'Leggere i rischi prima di proseguire.'],
  ['12. Deploy', 'Applicazione delle risorse e attesa che l’applicazione sia pronta (fino a 3 minuti).', 'Se non diventa pronta, aprire il Centro Operativo.'],
], [1.7, 5, 3.3]);
H2('10.3 Rischi segnalati dal wizard');
TABLE(['Rischio', 'Perché conta'], [
  ['Replica singola', 'Un guasto o un riavvio rende l’applicazione momentaneamente non disponibile.'],
  ['Repliche a zero', 'L’applicazione viene creata ma non avviata.'],
  ['Tag “latest”', 'Versioni diverse possono finire su nodi diversi; il rollback diventa incerto.'],
  ['Nessun limite di memoria / nessuna request', 'Il container può consumare risorse di altri o essere terminato in modo imprevedibile.'],
  ['Nessuna readiness / liveness probe', 'Traffico verso copie non pronte; container bloccati non riavviati.'],
  ['Disco RWO con più repliche', 'Il volume non può essere montato da più copie su nodi diversi.'],
  ['NodePort / LoadBalancer', 'L’applicazione è esposta direttamente all’esterno del cluster.'],
  ['Ingress senza TLS', 'Il traffico viaggia in chiaro.'],
  ['Segreti nelle variabili d’ambiente', 'Le password devono stare in un Secret, non nel testo della configurazione.'],
  ['Risorse esistenti da sovrascrivere', 'Il deploy aggiornerebbe un’applicazione già presente con lo stesso nome.'],
], [3, 7]);

// ------------------------------------------------------------------
H1('11. Operazioni sulle applicazioni');
LEAD('Le operazioni che modificano il sistema sono raccolte nel gruppo **Operazioni** e sono disponibili anche nelle pagine di dettaglio. Prima di ognuna Scarlet mostra una finestra di conferma con risorsa, namespace, conseguenze, possibile disservizio e livello di rischio.');
H2('11.1 Conferme e conferma digitata');
P('Le operazioni a rischio alto richiedono di **digitare il nome della risorsa** prima di poter confermare: è una protezione contro il clic sbagliato. Succede per esempio per l’eliminazione di qualsiasi risorsa diversa da un Pod gestito, per la riduzione a zero repliche, per il riavvio di un Pod non gestito da un controller, per il drain di un nodo e per l’arresto di un container Podman.');
H2('11.2 Le operazioni e il loro rischio');
TABLE(['Operazione', 'Effetto', 'Disservizio', 'Rischio'], [
  ['Scala (aumentare)', 'Avvia nuove copie.', 'Nessuno.', 'Basso'],
  ['Scala (ridurre)', 'Termina alcune copie.', 'Capacità ridotta.', 'Medio'],
  ['Scala a 0', 'Ferma l’applicazione.', 'Totale.', 'Alto (conferma digitata)'],
  ['Riavvia (rolling restart)', 'Ricrea i Pod uno alla volta.', 'Nessuno con 2+ repliche e readiness probe.', 'Medio'],
  ['Riavvia un Pod', 'Elimina il Pod; il controller ne crea uno nuovo.', 'Breve, solo per le richieste di quel Pod.', 'Medio'],
  ['Pausa / Riprendi rollout', 'Sospende o riprende l’applicazione delle modifiche.', 'Nessuno.', 'Basso'],
  ['Rollback', 'Torna al template di una revisione precedente.', 'Nessuno con rolling update e probe.', 'Medio'],
  ['Sospendi / Esegui ora (CronJob)', 'Ferma le esecuzioni pianificate o ne avvia una subito.', 'Nessuno.', 'Basso'],
  ['Elimina', 'Rimuove definitivamente la risorsa.', 'Dipende dalla risorsa.', 'Medio–Alto'],
  ['Elimina Namespace / PVC / PV / Secret', 'Rimuove dati o interi ambienti.', 'Totale, possibile perdita di dati.', 'Alto, irreversibile'],
], [2.4, 3.3, 2.4, 1.9]);
H2('11.3 Rollout e rollback');
P('**Operazioni → Rollout** mostra per un Deployment lo stato dell’aggiornamento, la strategia, le condizioni e la **cronologia delle revisioni** (versione, immagini, motivo, data). Si possono confrontare due revisioni (**Confronta**) e tornare a una precedente (**Rollback a questa revisione**). Il rollback crea una nuova revisione: è sempre possibile tornare indietro di nuovo.');
H2('11.4 Applicare YAML');
P('**Operazioni → Applica YAML** è riservato a chi conosce Kubernetes: permette di incollare uno o più documenti YAML, validarli sul cluster, vedere le differenze con le risorse esistenti e applicarli dopo una conferma. Gli Operator possono applicare solo i tipi legati alle applicazioni; gli altri tipi (namespace, Secret, volumi persistenti…) richiedono un amministratore. In caso di conflitto con modifiche fatte da altri strumenti, solo un amministratore può forzare l’applicazione.');

// ------------------------------------------------------------------
H2('11.5 Creare Job, Secret, ConfigMap e altre risorse');
P('Per le applicazioni ci sono i wizard (capitolo 10). Per tutti gli altri tipi di risorsa ogni elenco ha il pulsante **Crea <tipo>** (ad esempio **Crea Job** in **Applicazioni → Jobs**, **Crea Secret** in **Configurazione → Secrets**). Il pulsante apre **Applica YAML** con un **modello già compilato e commentato in italiano**, con il namespace selezionato nell’elenco. Gli stessi modelli si scelgono anche dal menu **Modello** della pagina Applica YAML.');
OL([
  'Aprire l’elenco del tipo di risorsa desiderato, scegliere il namespace e premere **Crea <tipo>**.',
  'Modificare i valori seguendo i commenti: nome, dati, immagine, orario…',
  'Premere **Valida**: Kubernetes verifica la risorsa senza crearla.',
  'Premere **Diff** per vedere cosa verrà creato o modificato.',
  'Premere **Applica** e confermare: la risorsa compare nell’elenco.',
]);
TABLE(['Modello', 'Cosa contiene', 'Ruolo necessario'], [
  ['ConfigMap', 'Variabili e file di configurazione non segreti.', 'Operator'],
  ['Secret', 'Credenziali in chiaro nel campo `stringData` (Kubernetes le codifica da solo) e un secondo esempio per l’accesso a un registry privato.', 'Administrator'],
  ['Job', 'Attività da completare una volta, con tentativi, tempo massimo e pulizia automatica.', 'Operator'],
  ['CronJob', 'Attività pianificata (esempio: ogni notte alle 02:30), senza esecuzioni sovrapposte.', 'Operator'],
  ['Service, Ingress', 'Accesso interno ed esterno a un’applicazione.', 'Operator'],
  ['PersistentVolumeClaim', 'Richiesta di disco persistente.', 'Operator'],
  ['StatefulSet, DaemonSet', 'Applicazioni con dati / agenti su ogni nodo.', 'Operator'],
  ['PodDisruptionBudget, HorizontalPodAutoscaler', 'Copie minime durante la manutenzione / scalatura automatica.', 'Operator'],
  ['Namespace', 'Nuovo spazio per un’applicazione o un ambiente.', 'Administrator'],
], [2.6, 5.4, 2]);
NOTE('warn', 'Attenzione.', 'nei modelli i valori di esempio (nomi, password, immagini) vanno sempre sostituiti. Le password vanno solo nei Secret, mai nelle variabili d’ambiente in chiaro.');

H1('12. Manutenzione');
H2('12.1 Manutenzione dei nodi');
P('Prima di spegnere o aggiornare una macchina del cluster si usa **Operazioni → Manutenzione** (solo amministratori):');
OL([
  '**Cordon** – il nodo non riceve più nuovi Pod; quelli in esecuzione restano dove sono.',
  '**Drain** – Scarlet mostra prima il **piano**: quali Pod verranno spostati, quali saltati (DaemonSet, Pod di sistema) e quali bloccano l’operazione (Pod non gestiti, dati temporanei) con il motivo. Dopo la conferma digitata, i Pod vengono spostati rispettando i PodDisruptionBudget; l’avanzamento è visibile in tempo reale e l’operazione può essere annullata.',
  'Eseguire la manutenzione della macchina.',
  '**Uncordon** – il nodo torna disponibile per nuovi Pod.',
]);
NOTE('warn', 'Attenzione.', 'il drain di un nodo che ospita l’unica copia di un’applicazione la interrompe finché non riparte altrove. Verificare prima la pagina **Alta affidabilità**.');
H2('12.2 Manutenzione dell’applicazione');
P('Nella stessa pagina gli amministratori trovano operazioni sullo stato di Scarlet: pulizia di sessioni scadute, audit oltre la conservazione e notifiche risolte vecchie; svuotamento della cache; ottimizzazione e verifica dell’integrità del database. Sono operazioni sicure, ciascuna con spiegazione e conferma.');

// ------------------------------------------------------------------
H1('13. Container Podman');
P('Il gruppo **Container** gestisce Podman sull’host di Scarlet. In ogni pagina un riquadro dichiara il runtime (**Podman**), lo stato della connessione, la versione e se Podman è in modalità rootless.');
TABLE(['Pagina', 'Funzioni'], [
  ['Container', 'Elenco con stato, immagine, porte e uso di CPU/memoria; avvio, arresto (conferma digitata), riavvio; eliminazione (solo amministratori). Il dettaglio mostra proprietà, configurazione (le variabili sensibili sono nascoste) e log.'],
  ['Immagini', 'Elenco con tag, dimensione e container che le usano; scaricamento ed eliminazione (amministratori); collegamento all’onboarding per verificarne il contenuto.'],
  ['Registry', 'Registry configurati in Podman e numero di immagini per registry.'],
], [2, 8]);
NOTE('warn', 'Attenzione.', 'Scarlet gestisce il Podman di sistema dell’host: chi può avviare container con quel Podman ha di fatto un controllo molto ampio sulla macchina. Per questo le operazioni sono limitate ai ruoli Operator e Administrator e tutte vengono registrate.');

// ------------------------------------------------------------------
H1('14. Monitoraggio');
H2('14.1 Da dove vengono le metriche');
UL([
  '**metrics-server** – uso attuale di CPU e memoria di nodi e Pod (presente nell’installazione attuale).',
  '**Prometheus** (facoltativo) – storico, traffico di rete e occupazione dei volumi. Se non è configurato, le pagine lo dichiarano invece di mostrare valori inventati.',
]);
H2('14.2 CPU e Memoria');
P('Per ogni nodo: uso reale rispetto alla capacità allocabile e quantità riservata dalle request dei Pod. Per i Pod: classifica per consumo, con la percentuale di memoria rispetto al limite (vicino al 100% significa rischio di OOMKilled).');
H2('14.3 Storage');
P('Richieste di volume con stato, capacità e StorageClass; capacità per tipo di storage; percentuale di occupazione dei volumi se Prometheus è configurato.');
H2('14.4 Health');
P('Lo stato di salute di Scarlet e dei componenti da cui dipende, ciascuno con stato **Healthy**, **Degraded** o **Unhealthy**: backend, database, Kubernetes, Podman, spazio su disco, configurazione, metrics-server, Prometheus e backup. I componenti facoltativi non rendono il sistema Unhealthy. Accanto ai problemi c’è il collegamento per intervenire.');
H2('14.5 Alta affidabilità');
P('Mostra quanto ogni applicazione resiste alla perdita di un Pod o di un nodo: repliche pronte, nodi su cui sono distribuite, presenza di un PodDisruptionBudget, strategia di aggiornamento, riavvii. Segnala in chiaro i punti deboli: replica singola, tutte le copie sullo stesso nodo, nessun PodDisruptionBudget, probe o risorse mancanti.');
H2('14.6 Eventi');
P('Tutti gli eventi del cluster, con i warning in evidenza e filtri per tipo, namespace e motivo; ogni evento porta alla risorsa coinvolta.');
H2('14.7 Il visualizzatore dei log');
TABLE(['Funzione', 'Descrizione'], [
  ['Selezione', 'Namespace, Pod e container (per i Pod con più container).'],
  ['Ultime righe', '100, 500, 1000, 2000 o 5000 righe.'],
  ['Esecuzione precedente', 'I log del container prima dell’ultimo riavvio: indispensabile per capire un CrashLoopBackOff.'],
  ['Live', 'Streaming in tempo reale, con **Pausa** (le righe vengono accumulate) e **Riprendi**. Per proteggere il sistema lo streaming si ferma da solo dopo 30 minuti o 20 000 righe: basta premere di nuovo Live.'],
  ['Cerca / filtra', 'Evidenzia il testo cercato o mostra solo le righe corrispondenti.'],
  ['Orari', 'Mostra o nasconde l’orario di ogni riga; errori e avvisi sono colorati.'],
  ['Scarica', 'Salva il log in un file (operazione registrata).'],
], [2.2, 7.8]);
NOTE('info', 'Nota.', 'i log possono contenere dati riservati: per questo non sono visibili al ruolo Viewer.');

// ------------------------------------------------------------------
H1('15. Ricerca globale e guida integrata');
H2('15.1 Ricerca globale');
P('Si apre con **Ctrl+K**, con il tasto **/** o con il campo nell’intestazione. Digitando almeno due caratteri cerca contemporaneamente in risorse Kubernetes (nomi, label, immagini), eventi, container e immagini Podman e articoli della guida. Le frecce scelgono il risultato e Invio lo apre. Per cercare un testo nei log, la ricerca propone di aprire il visualizzatore dei log con il filtro già impostato.');
H2('15.2 Guida integrata');
P('Il menu **Guida** contiene 57 articoli in italiano e inglese, organizzati in: introduzione, concetti fondamentali, applicazioni, networking, storage, configurazione, affidabilità, troubleshooting, procedure operative e FAQ. Gli articoli sui concetti hanno sempre la stessa struttura: spiegazione semplice, dettagli tecnici, esempio, cosa può andare storto, come verificare, come risolvere.');
P('La guida è **contestuale**: ogni pagina di Scarlet propone l’articolo pertinente (“Cos’è un Deployment?”) e ogni problema diagnosticato rimanda alla relativa procedura di risoluzione (“Come risolvere ImagePullBackOff”).');
NOTE('tip', 'Suggerimento.', 'prima di usare Scarlet in produzione leggere almeno gli articoli **Introduzione**, **Troubleshooting**, **Gestire un incidente** e quelli sui tipi di risorsa che si gestiranno più spesso.');

// ------------------------------------------------------------------
H1('16. Sicurezza e tracciabilità');
H2('16.1 Utenti (amministratori)');
P('**Sicurezza → Utenti** permette di creare utenti con un ruolo, modificarne ruolo e dati, disattivarli, reimpostare la password (con cambio obbligatorio al primo accesso), sbloccarli ed eliminarli (con conferma digitata). Non è possibile eliminare il proprio account né rimuovere l’ultimo amministratore attivo.');
H2('16.2 Ruoli e permessi');
P('Le pagine **Ruoli** e **Permessi** descrivono cosa può fare ciascun ruolo, con la matrice completa dei permessi spiegati in linguaggio semplice.');
H2('16.3 Audit Log');
P('Ogni operazione significativa viene registrata: accessi (riusciti e falliti), operazioni sulle risorse, visualizzazione dei Secret, download dei log, gestione utenti, impostazioni, backup, operazioni negate per mancanza di permessi. Ogni voce riporta utente, orario, azione, risorsa, namespace, esito (riuscita, fallita, negata) e indirizzo di provenienza. L’audit log è consultabile dagli amministratori con ricerca, filtri per utente, azione, esito, namespace e periodo, dettaglio completo ed esportazione CSV. Le voci sono conservate per 365 giorni (configurabile).');
NOTE('info', 'Nota.', 'password, token e valori dei Secret non vengono mai scritti nell’audit.');
H2('16.4 Buone pratiche di sicurezza per gli utenti');
UL([
  'Non condividere mai le credenziali: l’audit attribuisce ogni operazione all’utente.',
  'Chiudere la sessione (**Esci**) al termine del lavoro, soprattutto su postazioni condivise.',
  'Chiedere il ruolo minimo necessario: chi deve solo consultare lavora come Viewer.',
  'Non incollare password o token in campi non destinati a contenerli (variabili d’ambiente in chiaro, descrizioni, ticket).',
]);

// ------------------------------------------------------------------
H1('17. Backup e ripristino');
H2('17.1 Cosa viene salvato');
TABLE(['Contenuto', 'Incluso'], [
  ['Database di Scarlet: utenti, audit log, impostazioni, notifiche, cronologia dei backup', 'Sì'],
  ['File di configurazione del server, credenziali di accesso al cluster, certificati TLS', 'Sì'],
  ['Esportazione YAML delle risorse delle applicazioni (facoltativa)', 'Sì, se richiesta (mai i Secret)'],
  ['Dati delle applicazioni (contenuto dei volumi persistenti, database applicativi)', '**No**'],
  ['Stato completo del cluster Kubernetes (etcd)', '**No**'],
], [7.5, 2.5]);
NOTE('warn', 'Attenzione.', 'il backup di Scarlet **non è un backup del cluster**: protegge Scarlet, non le applicazioni. I dati delle applicazioni richiedono strumenti dedicati, concordati con l’amministratore di sistema.');
H2('17.2 Quando e dove');
P('Un backup automatico viene eseguito ogni notte (alle 02:30 circa) e conservato secondo la politica impostata (14 copie per impostazione predefinita). Gli archivi contengono informazioni riservate e sono accessibili solo agli amministratori.');
H2('17.3 La pagina Backup');
P('**Operazioni → Backup** mostra cosa viene salvato, l’ultimo backup, la cronologia (data, origine manuale o pianificata, dimensione, impronta di controllo, esito della verifica) e permette agli amministratori di eseguire un backup immediato, **verificarlo** (integrità dell’archivio e del database), scaricarlo ed eliminarlo.');
H2('17.4 Ripristino');
P('Il ripristino sostituisce lo stato di Scarlet con quello di un backup e richiede di fermare il servizio: per sicurezza non si esegue dall’interfaccia ma da un amministratore di sistema sul server, con la procedura descritta in `BACKUP.md` e nell’articolo della guida “Ripristinare un backup”. La pagina Backup mostra i comandi esatti per il file selezionato.');

// ------------------------------------------------------------------
H1('18. Impostazioni');
P('Il gruppo **Impostazioni** è visibile in lettura agli Operator e modificabile dagli amministratori.');
TABLE(['Sezione', 'Contenuto'], [
  ['Sistema', 'Informazioni in sola lettura: modalità, ambiente, file di configurazione, indirizzo e porta, TLS, database, versioni.'],
  ['Kubernetes', 'Connessione al cluster (kubeconfig, contesto), tempi di risposta; monitoraggio e Prometheus.'],
  ['Podman', 'Indirizzo dell’API di Podman e tempi di risposta.'],
  ['Logging', 'Livello di dettaglio dei log del server e limiti del visualizzatore dei log.'],
  ['Backup', 'Numero di copie conservate, esportazione dei manifest, conservazione dell’audit.'],
  ['Autenticazione', 'Durata delle sessioni, tentativi prima del blocco, durata del blocco, lunghezza minima della password.'],
], [2, 8]);
P('Accanto a ogni valore Scarlet indica se proviene dal **file** di configurazione del server o è stato modificato dall’**interfaccia**; **Ripristina valori del file** annulla le modifiche fatte dall’interfaccia per quella sezione. Ogni modifica è registrata nell’audit.');

// ------------------------------------------------------------------
H1('19. Regole d’oro per operare in sicurezza');
OL([
  '**Guardare sempre l’etichetta LIVE/DEMO** prima di agire.',
  '**Partire dal Centro Operativo**, non da un’ipotesi: leggere la causa più probabile e i controlli.',
  '**Leggere i log prima di riavviare**: un riavvio nasconde la causa e raramente risolve un errore di configurazione.',
  '**Una modifica alla volta**, verificandone l’effetto prima della successiva.',
  '**Preferire il rollback** quando un problema nasce subito dopo un aggiornamento: è rapido e reversibile.',
  '**Leggere conseguenze e rischio** nelle finestre di conferma: sono scritte per essere lette.',
  '**Mai eliminare** namespace, volumi o Secret senza aver verificato con chi li possiede.',
  '**Segnare come gestito** il problema che si prende in carico, così il resto del team lo sa.',
  '**Controllare la pagina Alta affidabilità** prima di manutenzioni e riavvii.',
  '**Verificare sempre il risultato**: stato dell’applicazione, Centro Operativo e notifiche dopo ogni intervento.',
]);

// ------------------------------------------------------------------
H1('20. Gestire un incidente: traccia operativa');
TABLE(['Fase', 'Cosa fare in Scarlet'], [
  ['1. Rilevare', 'Dashboard o notifiche segnalano il problema; aprire il Centro Operativo.'],
  ['2. Prendere in carico', 'Segnare il problema come gestito, così gli altri sanno che qualcuno se ne occupa.'],
  ['3. Delimitare', 'Quali applicazioni, quali Pod, quale nodo? Usare la scheda Relazioni e il filtro per namespace.'],
  ['4. Diagnosticare', 'Leggere controlli e causa probabile, eventi, log (anche dell’esecuzione precedente), metriche.'],
  ['5. Decidere', 'Scegliere l’intervento meno invasivo: correzione della configurazione, rollback, scalatura, riavvio. Valutare il rischio indicato.'],
  ['6. Agire', 'Eseguire l’operazione con le conferme previste.'],
  ['7. Verificare', 'Attendere che l’applicazione torni integra; il problema passa automaticamente a “risolto”.'],
  ['8. Documentare', 'L’audit log contiene chi ha fatto cosa e quando: utilizzarlo per il resoconto dell’incidente.'],
], [2, 8]);

// ------------------------------------------------------------------
H1('21. Domande frequenti');
const faq = (q, a) => { H3(q); P(a); };
faq('Perché non vedo il pulsante Scala o Elimina?', 'Il proprio ruolo non lo consente. Le azioni non permesse non vengono mostrate; in ogni caso il server le rifiuterebbe.');
faq('Perché non vedo i log?', 'Il ruolo Viewer non ha accesso ai log, che possono contenere dati riservati.');
faq('La pagina dice “Metriche avanzate non configurate”: è un errore?', 'No: indica che la sorgente delle metriche richiesta (metrics-server o Prometheus) non è disponibile. Scarlet non inventa valori.');
faq('Ho riavviato un Pod e il problema è tornato. Perché?', 'Il riavvio non corregge la causa. Leggere i log dell’esecuzione precedente e i controlli della scheda problema.');
faq('Che differenza c’è tra eliminare un Pod e riavviare un Deployment?', 'Eliminando un Pod gestito, il controller ne crea uno nuovo; il riavvio del Deployment ricrea tutti i Pod uno alla volta senza interrompere il servizio.');
faq('Posso annullare un’eliminazione?', 'No. Per questo le eliminazioni importanti richiedono di digitare il nome della risorsa.');
faq('Il problema è sparito dal Centro Operativo: è risolto?', 'Sì: Scarlet lo segna come risolto quando non lo rileva più. Le notifiche risolte restano consultabili per 30 giorni.');
faq('Scarlet è lento o non risponde.', 'Controllare la pagina **Health**: se Kubernetes risponde lentamente, anche Scarlet ne risente. Gli errori spiegano se la causa è la rete, il cluster o le credenziali.');
faq('Ho dimenticato la password.', 'Chiedere a un amministratore di reimpostarla da Sicurezza → Utenti.');

// ------------------------------------------------------------------
H1('22. Glossario');
TABLE(['Termine', 'Definizione'], [
  ['Audit log', 'Registro delle operazioni significative: chi, cosa, quando, con quale esito.'],
  ['Cordon / Drain / Uncordon', 'Escludere un nodo dai nuovi Pod / spostarne i Pod / rimetterlo in servizio.'],
  ['CrashLoopBackOff', 'Container che termina subito dopo l’avvio e viene riavviato con attese crescenti.'],
  ['Dry-run', 'Prova di un’operazione sul cluster senza applicarla, per verificarne la validità.'],
  ['Evento', 'Messaggio di Kubernetes su ciò che accade a una risorsa.'],
  ['ImagePullBackOff', 'Impossibilità di scaricare l’immagine del container.'],
  ['Kubeconfig', 'File con l’indirizzo del cluster e le credenziali usate da Scarlet.'],
  ['metrics-server', 'Componente del cluster che misura l’uso di CPU e memoria.'],
  ['OOMKilled', 'Container terminato perché ha superato il limite di memoria.'],
  ['Pending', 'Pod in attesa di essere assegnato a un nodo o di partire.'],
  ['Probe (readiness / liveness)', 'Controlli di salute: pronto a ricevere traffico / da riavviare perché bloccato.'],
  ['Registry', 'Archivio da cui si scaricano le immagini dei container.'],
  ['Replica', 'Copia identica di un’applicazione.'],
  ['Request / Limit', 'Risorse riservate / massime per un container.'],
  ['Revisione', 'Una versione del template di un Deployment, usata per il rollback.'],
  ['Rolling update', 'Aggiornamento progressivo, una copia alla volta.'],
  ['YAML', 'Formato testuale con cui si descrivono le risorse Kubernetes.'],
], [3, 7]);

// ------------------------------------------------------------------
H1('Appendice A – Riferimento rapido');
H2('A.1 Scorciatoie');
TABLE(['Tasto', 'Funzione'], [
  ['Ctrl+K oppure /', 'Apre la ricerca globale.'],
  ['↑ ↓ e Invio', 'Scorre e apre i risultati della ricerca.'],
  ['Esc', 'Chiude finestre di dialogo e pannelli.'],
  ['← → sulle schede', 'Passa alla scheda precedente o successiva.'],
  ['Alt+← / Alt+→ nei wizard', 'Passo precedente / successivo.'],
], [3, 7]);
H2('A.2 Messaggi di errore più comuni');
TABLE(['Messaggio', 'Significato', 'Cosa fare'], [
  ['Impossibile ottenere lo stato del cluster', 'Scarlet non raggiunge Kubernetes.', 'Pagina Health; avvisare l’amministratore.'],
  ['Credenziali Kubernetes rifiutate', 'Le credenziali di Scarlet verso il cluster non sono più valide.', 'Avvisare l’amministratore.'],
  ['Permessi Kubernetes insufficienti', 'L’identità di Scarlet nel cluster non può eseguire l’operazione.', 'Avvisare l’amministratore.'],
  ['Operazione non consentita', 'Il proprio ruolo in Scarlet non lo permette.', 'Chiedere il permesso a un amministratore.'],
  ['Risorsa non trovata', 'La risorsa non esiste più (es. Pod ricreato).', 'Tornare all’elenco e aggiornare.'],
  ['Kubernetes ha rifiutato la configurazione', 'Uno o più campi non sono validi.', 'Leggere i campi indicati e correggerli.'],
  ['Troppe richieste', 'Limite di richieste superato.', 'Attendere i secondi indicati.'],
  ['Podman non raggiungibile', 'Scarlet non comunica con Podman.', 'Pagina Health; avvisare l’amministratore.'],
], [3.2, 3.6, 3.2]);

H1('Appendice B – L’installazione attuale');
P('Riferimenti dell’ambiente su cui è installato Scarlet alla data di questa edizione.');
TABLE(['Voce', 'Valore'], [
  ['Indirizzo', '`https://mv3412.farm.ised.it:8443` (anche `https://10.20.23.64:8443`)'],
  ['Versione di Scarlet', VERSION],
  ['Sistema operativo del server', 'Oracle Linux Server 9.8, x86_64'],
  ['Kubernetes', 'k3s v1.36.5, nodo singolo `mv3412`, con metrics-server e storage local-path'],
  ['Podman', '5.8.2 (rootful)'],
  ['Identità di Scarlet nel cluster', 'ServiceAccount `pkm` nel namespace `pkm-system`, ruolo `pkm-operator`'],
  ['Backup automatico', 'Ogni notte alle 02:30 circa, 14 copie conservate'],
  ['Certificato', 'Autofirmato generato all’installazione (da sostituire con un certificato aziendale)'],
], [3, 7]);
NOTE('info', 'Nota.', 'per installazione, aggiornamento, disinstallazione e gestione del server fare riferimento alla documentazione tecnica (`INSTALL.md`, `OPERATIONS.md`, `TROUBLESHOOTING.md`).');

// ------------------------------------------------------------------ documento
const footer = new Footer({
  children: [new Paragraph({
    style: 'PiePagina',
    tabStops: [{ type: TabStopType.RIGHT, position: CONTENT_W }],
    border: { top: { style: BorderStyle.SINGLE, size: 4, color: 'D5CCCC', space: 6 } },
    children: [
      new TextRun('© 2026 ISED – Tutti i diritti riservati'),
      new TextRun({ children: [new Tab(), `Scarlet v${VERSION}`] }),
    ],
  })],
});
const header = new Header({
  children: [new Paragraph({
    style: 'PiePagina',
    tabStops: [{ type: TabStopType.RIGHT, position: CONTENT_W }],
    children: [
      new TextRun({ text: 'Scarlet – Guida utente', color: GREY }),
      new TextRun({ children: [new Tab(), 'Pagina ', PageNumber.CURRENT, ' di ', PageNumber.TOTAL_PAGES], color: GREY }),
    ],
  })],
});

const doc = new Document({
  creator: 'ISED',
  title: 'Scarlet – Guida utente',
  description: `Guida utente di Scarlet ${VERSION}`,
  features: { updateFields: true },
  fonts: [{ name: FONT, data: fs.readFileSync(path.join(__dirname, '..', 'fonts', 'PT_Sans-Narrow-Web-Regular.ttf')) }],
  styles: {
    default: { document: { run: { font: FONT, size: 22, color: DARK }, paragraph: { spacing: { after: 120, line: 288 } } } },
    paragraphStyles: [
      { id: 'Title', name: 'Title', basedOn: 'Normal', run: { font: FONT, size: 72, bold: true, color: RED } },
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 40, bold: true, color: RED }, paragraph: { spacing: { before: 0, after: 240 }, keepNext: true, outlineLevel: 0, border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: RED, space: 6 } } } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 30, bold: true, color: DARK }, paragraph: { spacing: { before: 300, after: 120 }, keepNext: true, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 24, bold: true, color: RED }, paragraph: { spacing: { before: 220, after: 80 }, keepNext: true, outlineLevel: 2 } },
      { id: 'Lead', name: 'Introduzione capitolo', basedOn: 'Normal', run: { size: 25, color: GREY, italics: true }, paragraph: { spacing: { after: 200 } } },
      { id: 'NotaInfo', name: 'Nota informativa', basedOn: 'Normal', run: { size: 21 }, paragraph: { spacing: { before: 120, after: 160 }, indent: { left: 200, right: 200 }, shading: { type: ShadingType.CLEAR, fill: 'EEF3FA', color: 'auto' }, border: { left: { style: BorderStyle.SINGLE, size: 24, color: '1D5FA8', space: 8 } } } },
      { id: 'NotaSuggerimento', name: 'Nota suggerimento', basedOn: 'Normal', run: { size: 21 }, paragraph: { spacing: { before: 120, after: 160 }, indent: { left: 200, right: 200 }, shading: { type: ShadingType.CLEAR, fill: 'EDF6EF', color: 'auto' }, border: { left: { style: BorderStyle.SINGLE, size: 24, color: '17703A', space: 8 } } } },
      { id: 'NotaAttenzione', name: 'Nota attenzione', basedOn: 'Normal', run: { size: 21 }, paragraph: { spacing: { before: 120, after: 160 }, indent: { left: 200, right: 200 }, shading: { type: ShadingType.CLEAR, fill: 'FBECEC', color: 'auto' }, border: { left: { style: BorderStyle.SINGLE, size: 24, color: RED, space: 8 } } } },
      { id: 'Nota', name: 'Nota', basedOn: 'Normal', run: { size: 18, color: GREY } },
      { id: 'Codice', name: 'Codice', basedOn: 'Normal', run: { font: MONO, size: 18 }, paragraph: { spacing: { after: 0, line: 240 }, shading: { type: ShadingType.CLEAR, fill: 'F2F2F2', color: 'auto' } } },
      { id: 'Tabella', name: 'Testo tabella', basedOn: 'Normal', run: { size: 20 }, paragraph: { spacing: { after: 40, line: 252 } } },
      { id: 'DopoTabella', name: 'Spazio dopo tabella', basedOn: 'Normal', run: { size: 8 }, paragraph: { spacing: { after: 120 } } },
      { id: 'PiePagina', name: 'Piè di pagina Scarlet', basedOn: 'Normal', run: { size: 18, color: GREY }, paragraph: { spacing: { after: 0 } } },
    ],
  },
  numbering: {
    config: [
      { reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 400, hanging: 260 } }, run: { color: RED } } }] },
      { reference: 'steps', levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 440, hanging: 300 } }, run: { bold: true, color: RED } } }] },
    ],
  },
  sections: [
    {
      properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134, footer: 567, header: 567 } } },
      footers: { default: footer },
      children: cover,
    },
    {
      properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1300, bottom: 1250, left: 1134, right: 1134, footer: 567, header: 567 } } },
      headers: { default: header },
      footers: { default: footer },
      children: [...toc, ...body],
    },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  const out = process.argv[2] || 'Scarlet-Guida-utente.docx';
  fs.writeFileSync(out, buf);
  console.log('written', out, buf.length, 'bytes');
});
