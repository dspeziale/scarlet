{{- define "scarlet.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "scarlet.fullname" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "scarlet.labels" -}}
app.kubernetes.io/name: {{ include "scarlet.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "scarlet.env" -}}
envFrom:
  - configMapRef:
      name: {{ include "scarlet.fullname" . }}-config
  - secretRef:
      name: {{ .Values.existingSecret }}
{{- end -}}

{{- define "scarlet.securityContext" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: ["ALL"]
{{- end -}}

{{- define "scarlet.volumes" -}}
volumes:
  - name: data
    {{- if .Values.persistence.enabled }}
    persistentVolumeClaim:
      claimName: {{ .Values.persistence.existingClaim | default (printf "%s-data" (include "scarlet.fullname" .)) }}
    {{- else }}
    emptyDir: {}
    {{- end }}
  - name: tmp
    emptyDir: {}
{{- end -}}
