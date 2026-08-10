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

{{- define "sein-zum-tode.ingressFullname" -}}
{{- printf "%s-ingress" (include "sein-zum-tode.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sein-zum-tode.pollingLeaseName" -}}
{{- default (printf "%s-polling" (include "sein-zum-tode.ingressFullname" .)) .Values.ingress.coordination.leaseName | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sein-zum-tode.ingressCoordinationName" -}}
{{- printf "%s-coordination" (include "sein-zum-tode.ingressFullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sein-zum-tode.ingressServiceAccountName" -}}
{{- if .Values.ingress.coordination.enabled }}
{{- if .Values.ingress.coordination.serviceAccount.create }}
{{- default (include "sein-zum-tode.ingressFullname" .) .Values.ingress.coordination.serviceAccount.name }}
{{- else }}
{{- required "ingress.coordination.serviceAccount.name is required when its creation is disabled" .Values.ingress.coordination.serviceAccount.name }}
{{- end }}
{{- else }}
{{- include "sein-zum-tode.serviceAccountName" . }}
{{- end }}
{{- end }}

{{- define "sein-zum-tode.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sein-zum-tode.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sein-zum-tode.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "sein-zum-tode.labels" -}}
helm.sh/chart: {{ include "sein-zum-tode.chart" . }}
{{ include "sein-zum-tode.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Chart.AppVersion }}
app.kubernetes.io/version: {{ . | quote }}
{{- end }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "sein-zum-tode.image" -}}
{{- if .Values.image.digest }}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else }}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) }}
{{- end }}
{{- end }}

{{- define "sein-zum-tode.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "sein-zum-tode.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "sein-zum-tode.defaultSecretName" -}}
{{- if .Values.secrets.defaultName }}
{{- .Values.secrets.defaultName }}
{{- else if and .Values.externalSecret.enabled .Values.externalSecret.targetName }}
{{- .Values.externalSecret.targetName }}
{{- else }}
{{- printf "%s-secrets" (include "sein-zum-tode.fullname" .) }}
{{- end }}
{{- end }}

{{- define "sein-zum-tode.secretRefName" -}}
{{- $root := index . 0 -}}
{{- $reference := index . 1 -}}
{{- default (include "sein-zum-tode.defaultSecretName" $root) $reference.name }}
{{- end }}

{{- define "sein-zum-tode.externalSecretName" -}}
{{- default (include "sein-zum-tode.defaultSecretName" .) .Values.externalSecret.targetName }}
{{- end }}

{{- define "sein-zum-tode.configMapName" -}}
{{- if .Values.applicationConfig.create }}
{{- printf "%s-bot-content" (include "sein-zum-tode.fullname" .) }}
{{- else }}
{{- required "applicationConfig.existingConfigMap is required when applicationConfig.create=false" .Values.applicationConfig.existingConfigMap }}
{{- end }}
{{- end }}

{{- define "sein-zum-tode.redisTlsMaterial" -}}
{{- if or .Values.redis.tls.secretRef.caKey .Values.redis.tls.secretRef.certificateKey .Values.redis.tls.secretRef.privateKeyKey }}true{{- end }}
{{- end }}

{{- define "sein-zum-tode.postgresTlsMaterial" -}}
{{- if or .Values.postgres.tls.secretRef.caKey .Values.postgres.tls.secretRef.certificateKey .Values.postgres.tls.secretRef.privateKeyKey }}true{{- end }}
{{- end }}

{{- define "sein-zum-tode.temporalTlsMaterial" -}}
{{- if or .Values.temporal.tls.secretRef.caKey .Values.temporal.tls.secretRef.certificateKey .Values.temporal.tls.secretRef.privateKeyKey }}true{{- end }}
{{- end }}
