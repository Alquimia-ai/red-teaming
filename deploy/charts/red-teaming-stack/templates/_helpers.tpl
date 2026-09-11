{{/* Labels every object carries. */}}
{{- define "red-teaming.labels" -}}
app.kubernetes.io/part-of: red-teaming
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{/* Where the S3 API answers: MinIO in the cluster, or what the values say. */}}
{{- define "red-teaming.storeEndpoint" -}}
{{- if .Values.minio.enabled -}}
http://red-teaming-minio.{{ .Release.Namespace }}.svc:9000
{{- else -}}
{{ .Values.store.endpoint }}
{{- end -}}
{{- end }}

{{/* Whether a store Secret exists to read credentials from. */}}
{{- define "red-teaming.hasStoreSecret" -}}
{{- if or .Values.minio.enabled (and .Values.store.accessKey .Values.store.secretKey) -}}true{{- end -}}
{{- end }}

{{/* The runner's wiring, shared by the API's ConfigMap and the runner's: same store, seen from both sides. */}}
{{- define "red-teaming.storeEnv" -}}
REDTEAM_STORE_BACKEND: "s3"
REDTEAM_S3_BUCKET: {{ .Values.store.bucket | quote }}
{{- with (include "red-teaming.storeEndpoint" .) }}
REDTEAM_S3_ENDPOINT: {{ . | quote }}
{{- end }}
{{- with .Values.store.region }}
REDTEAM_S3_REGION: {{ . | quote }}
{{- end }}
REDTEAM_SECRETS_BACKEND: "env"
REDTEAM_BRAIN_REGISTRY_INSECURE: {{ .Values.brainRegistry.insecure | quote }}
{{- with .Values.brainRegistry.secretRef }}
REDTEAM_BRAIN_REGISTRY_SECRET_REF: {{ . | quote }}
{{- end }}
{{- end }}
