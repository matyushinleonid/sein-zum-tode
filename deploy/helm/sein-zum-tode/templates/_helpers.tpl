{{- define "sein-zum-tode.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sein-zum-tode.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "sein-zum-tode.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{ include "sein-zum-tode.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "sein-zum-tode.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sein-zum-tode.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "sein-zum-tode.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "sein-zum-tode.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "sein-zum-tode.secretName" -}}
{{- if .Values.externalSecret.enabled }}
{{- default (printf "%s-secrets" (include "sein-zum-tode.fullname" .)) .Values.externalSecret.targetName }}
{{- else }}
{{- required "existingSecret is required when externalSecret.enabled=false" .Values.existingSecret }}
{{- end }}
{{- end }}
