{{/*
Noms standard du chart : helpers réutilisables dans tous les templates.
*/}}

{{/* Nom de base du release (tronqué à 63 chars) */}}
{{- define "pcb-ai.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Nom complet : release-name (tronqué) */}}
{{- define "pcb-ai.fullname" -}}
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

{{/* Nom du ConfigMap applicatif */}}
{{- define "pcb-ai.configName" -}}
{{- printf "%s-config" (include "pcb-ai.fullname" .) }}
{{- end }}

{{/* Nom du Secret applicatif */}}
{{- define "pcb-ai.secretName" -}}
{{- printf "%s-secret" (include "pcb-ai.fullname" .) }}
{{- end }}

{{/* Labels standard appliqués à toutes les ressources */}}
{{- define "pcb-ai.labels" -}}
app.kubernetes.io/name: {{ include "pcb-ai.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/part-of: pcb-ai-designer-v3
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end }}

{{/* Labels de sélection pour un composant donné (args : "component") */}}
{{- define "pcb-ai.selectorLabels" -}}
app.kubernetes.io/name: {{ include "pcb-ai.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: {{ . }}
{{- end }}

{{/* Environnement applicatif commun (envFrom config+secret) */}}
{{- define "pcb-ai.envFrom" -}}
envFrom:
  - configMapRef:
      name: {{ include "pcb-ai.configName" . }}
  - secretRef:
      name: {{ include "pcb-ai.secretName" . }}
{{- end }}
