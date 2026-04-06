{{/*
Autor:   Diego Regis M. F. dos Santos
Email:   diego-f-santos@openlabs.com.br
Time:    OpenLabs - DevOps | Infra
Versão:  2.0.0
Arquivo: helm/status-report/templates/_helpers.tpl
*/}}

{{- define "status-report.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "status-report.fullname" -}}
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

{{- define "status-report.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "status-report.labels" -}}
helm.sh/chart: {{ include "status-report.chart" . }}
{{ include "status-report.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: openlab-devops
{{- end }}

{{- define "status-report.selectorLabels" -}}
app.kubernetes.io/name: {{ include "status-report.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "status-report.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "status-report.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "status-report.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion }}
{{- printf "%s:%s" .Values.image.repository $tag }}
{{- end }}

{{/* Secret name para SMTP */}}
{{- define "status-report.smtpSecretName" -}}
{{- if .Values.smtp.existingSecret }}
{{- .Values.smtp.existingSecret }}
{{- else }}
{{- include "status-report.fullname" . }}-smtp
{{- end }}
{{- end }}

{{/* Secret name para Teams */}}
{{- define "status-report.teamsSecretName" -}}
{{- if .Values.teams.existingSecret }}
{{- .Values.teams.existingSecret }}
{{- else }}
{{- include "status-report.fullname" . }}-webhooks
{{- end }}
{{- end }}

{{/* Namespace do release */}}
{{- define "status-report.namespace" -}}
{{- default .Release.Namespace .Values.namespaceOverride }}
{{- end }}
