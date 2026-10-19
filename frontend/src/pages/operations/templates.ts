// Ready-to-edit YAML templates used by "Crea" on the resource lists and by Applica YAML.
// Comments explain each field in plain language; the namespace is filled in automatically.

export interface ResourceTemplate {
  key: string; // kind key (configmaps, secrets, ...)
  kind: string;
  namespaced: boolean;
  /** Needs resources.apply (administrator) instead of workloads.deploy (operator). */
  adminOnly: boolean;
  yaml: (ns: string) => string;
}

const t = (key: string, kind: string, namespaced: boolean, adminOnly: boolean, yaml: (ns: string) => string): ResourceTemplate => ({
  key,
  kind,
  namespaced,
  adminOnly,
  yaml,
});

export const TEMPLATES: ResourceTemplate[] = [
  t('configmaps', 'ConfigMap', true, false, (ns) => `# ConfigMap: configurazione NON segreta dell'applicazione (variabili o file).
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-config            # nome: minuscole, numeri e trattini
  namespace: ${ns}
data:
  LOG_LEVEL: info            # una chiave per ogni valore
  app.properties: |          # oppure il contenuto di un file intero
    feature.x=true
    timeout=30
`),
  t('secrets', 'Secret', true, true, (ns) => `# Secret: dati riservati (password, token, certificati).
# In "stringData" i valori si scrivono in chiaro: Kubernetes li codifica da solo.
# Dopo la creazione Scarlet li mostra nascosti; solo gli amministratori possono vederli (con audit).
apiVersion: v1
kind: Secret
metadata:
  name: my-credentials
  namespace: ${ns}
type: Opaque
stringData:
  DB_USER: app
  DB_PASSWORD: cambia-questa-password
---
# Secret per scaricare immagini da un registry privato (da usare in imagePullSecrets).
# Sostituire l'intero valore di .dockerconfigjson con quello del proprio registry.
apiVersion: v1
kind: Secret
metadata:
  name: my-registry
  namespace: ${ns}
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
    {"auths": {"registry.example.com": {"username": "utente", "password": "password"}}}
`),
  t('jobs', 'Job', true, false, (ns) => `# Job: esegue un'attività fino al completamento (es. una migrazione) e poi si ferma.
apiVersion: batch/v1
kind: Job
metadata:
  name: my-job
  namespace: ${ns}
spec:
  backoffLimit: 2               # tentativi in caso di errore
  activeDeadlineSeconds: 600    # tempo massimo (secondi)
  ttlSecondsAfterFinished: 86400  # il Job completato viene rimosso dopo 1 giorno
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: task
          image: docker.io/library/busybox:1.36
          command: ["sh", "-c", "echo 'Lavoro eseguito'; sleep 5"]
          resources:
            requests: { cpu: 100m, memory: 64Mi }
            limits: { memory: 128Mi }
`),
  t('cronjobs', 'CronJob', true, false, (ns) => `# CronJob: crea un Job a orari stabiliti (formato cron: minuto ora giorno mese giorno-settimana).
apiVersion: batch/v1
kind: CronJob
metadata:
  name: my-nightly-task
  namespace: ${ns}
spec:
  schedule: "30 2 * * *"         # ogni notte alle 02:30
  concurrencyPolicy: Forbid      # non avviare una nuova esecuzione se la precedente è ancora in corso
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      backoffLimit: 1
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: task
              image: docker.io/library/busybox:1.36
              command: ["sh", "-c", "date; echo 'Attività pianificata'"]
              resources:
                requests: { cpu: 100m, memory: 64Mi }
                limits: { memory: 128Mi }
`),
  t('services', 'Service', true, false, (ns) => `# Service: nome e indirizzo stabili per raggiungere i Pod di un'applicazione.
apiVersion: v1
kind: Service
metadata:
  name: my-app
  namespace: ${ns}
spec:
  type: ClusterIP                # ClusterIP = solo interno; NodePort/LoadBalancer = esposto all'esterno
  selector:
    app.kubernetes.io/name: my-app   # deve corrispondere alle label dei Pod
  ports:
    - name: http
      port: 80                   # porta del Service
      targetPort: 8080           # porta del container
`),
  t('ingresses', 'Ingress', true, false, (ns) => `# Ingress: rende un'applicazione web raggiungibile dall'esterno con un nome host.
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
  namespace: ${ns}
spec:
  # ingressClassName: nginx      # classe dell'Ingress Controller installato nel cluster
  rules:
    - host: my-app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-app       # Service di destinazione
                port: { number: 80 }
  # tls:
  #   - hosts: [my-app.example.com]
  #     secretName: my-app-tls   # Secret di tipo kubernetes.io/tls
`),
  t('persistentvolumeclaims', 'PersistentVolumeClaim', true, false, (ns) => `# PersistentVolumeClaim: richiesta di spazio disco persistente per un'applicazione.
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-data
  namespace: ${ns}
spec:
  accessModes: [ReadWriteOnce]   # montabile da un solo nodo alla volta
  # storageClassName: local-path # vuoto = StorageClass predefinita del cluster
  resources:
    requests:
      storage: 5Gi
`),
  t('statefulsets', 'StatefulSet', true, false, (ns) => `# StatefulSet: applicazione con dati (es. database), con nome stabile e disco proprio per ogni copia.
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: my-db
  namespace: ${ns}
spec:
  serviceName: my-db
  replicas: 1
  selector:
    matchLabels: { app.kubernetes.io/name: my-db }
  template:
    metadata:
      labels: { app.kubernetes.io/name: my-db }
    spec:
      containers:
        - name: db
          image: docker.io/library/postgres:16
          env:
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef: { name: my-credentials, key: DB_PASSWORD }   # mai password in chiaro qui
          ports: [{ containerPort: 5432, name: db }]
          resources:
            requests: { cpu: 250m, memory: 512Mi }
            limits: { memory: 1Gi }
          volumeMounts: [{ name: data, mountPath: /var/lib/postgresql/data }]
  volumeClaimTemplates:
    - metadata: { name: data }
      spec:
        accessModes: [ReadWriteOnce]
        resources: { requests: { storage: 10Gi } }
`),
  t('daemonsets', 'DaemonSet', true, false, (ns) => `# DaemonSet: una copia su ogni nodo (agenti di monitoraggio, raccolta log...).
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: my-agent
  namespace: ${ns}
spec:
  selector:
    matchLabels: { app.kubernetes.io/name: my-agent }
  template:
    metadata:
      labels: { app.kubernetes.io/name: my-agent }
    spec:
      containers:
        - name: agent
          image: docker.io/library/busybox:1.36
          command: ["sh", "-c", "while true; do date; sleep 60; done"]
          resources:
            requests: { cpu: 50m, memory: 32Mi }
            limits: { memory: 64Mi }
`),
  t('poddisruptionbudgets', 'PodDisruptionBudget', true, false, (ns) => `# PodDisruptionBudget: durante la manutenzione dei nodi resta attivo almeno questo numero di copie.
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app
  namespace: ${ns}
spec:
  minAvailable: 1
  selector:
    matchLabels: { app.kubernetes.io/name: my-app }
`),
  t('horizontalpodautoscalers', 'HorizontalPodAutoscaler', true, false, (ns) => `# HorizontalPodAutoscaler: aumenta o riduce le repliche in base all'uso di CPU (richiede metrics-server).
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app
  namespace: ${ns}
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: my-app }
  minReplicas: 2
  maxReplicas: 6
  metrics:
    - type: Resource
      resource:
        name: cpu
        target: { type: Utilization, averageUtilization: 70 }
`),
  t('namespaces', 'Namespace', false, true, () => `# Namespace: uno spazio separato per un'applicazione o un ambiente (es. produzione, collaudo).
apiVersion: v1
kind: Namespace
metadata:
  name: my-namespace
`),
];

export function templateFor(key: string | null | undefined): ResourceTemplate | undefined {
  return TEMPLATES.find((x) => x.key === key);
}
