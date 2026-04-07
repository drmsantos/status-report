#!/bin/bash
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versão:  1.0.0
# Arquivo: install.sh
# Desc:    Instalador interativo do K8s Status Report — multi-cliente
# Uso:
#   bash install.sh                    # interativo
#   bash install.sh --uninstall        # remove instalação existente
# =============================================================================

set -euo pipefail

# ── Cores ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}  ✓ $*${NC}"; }
warn() { echo -e "${YELLOW}  ! $*${NC}"; }
err()  { echo -e "${RED}  ✗ $*${NC}"; }
step() { echo -e "\n${CYAN}${BOLD}▶ $*${NC}"; }
ask()  { echo -e "${YELLOW}  $*${NC}"; }

CHART_DIR="$(cd "$(dirname "$0")" && pwd)/helm/status-report"
VALUES_DIR="$(cd "$(dirname "$0")" && pwd)/values"
mkdir -p "$VALUES_DIR"

# ── Banner ────────────────────────────────────────────────────────────────────
echo -e "${CYAN}${BOLD}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       K8s Status Report — Instalador v1.0.0                 ║"
echo "║       OpenLabs DevOps | Infra                                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Uninstall ─────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
    ask "Nome do release para remover (ex: status-report-clienteA): "
    read -r RELEASE
    ask "Namespace: "
    read -r NS
    helm uninstall "$RELEASE" -n "$NS" || true
    kubectl delete namespace "$NS" --ignore-not-found
    ok "Removido: $RELEASE / $NS"
    exit 0
fi

# ── Pré-requisitos ────────────────────────────────────────────────────────────
step "Verificando pré-requisitos"

for bin in kubectl helm; do
    if command -v "$bin" &>/dev/null; then
        ok "$bin encontrado"
    else
        err "$bin não encontrado — instale antes de continuar"
        exit 1
    fi
done

# ── Detecta tipo de cluster ───────────────────────────────────────────────────
step "Detectando cluster"

CURRENT_CTX=$(kubectl config current-context 2>/dev/null || echo "")
if [[ -z "$CURRENT_CTX" ]]; then
    err "Nenhum contexto kubectl ativo. Configure o kubeconfig antes de continuar."
    exit 1
fi
ok "Contexto ativo: $CURRENT_CTX"

# Detecta plataforma
if kubectl api-resources --api-group=route.openshift.io --no-headers 2>/dev/null | grep -q route; then
    PLATFORM="openshift"
    ok "Plataforma detectada: OpenShift"
else
    PLATFORM="kubernetes"
    ok "Plataforma detectada: Kubernetes / RKE2"
fi

SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null || echo "?")
ok "API server: $SERVER"

# ── Identidade do cliente ─────────────────────────────────────────────────────
step "Identidade do cliente"

ask "Nome do cliente/ambiente (ex: openlabs, vtal-hml, clienteA): "
read -r CLIENT_NAME
CLIENT_NAME="${CLIENT_NAME// /-}"          # substitui espaços por hífen
CLIENT_NAME=$(echo "$CLIENT_NAME" | tr '[:upper:]' '[:lower:]')

RELEASE="status-report-${CLIENT_NAME}"
NAMESPACE="status-report-${CLIENT_NAME}"

ok "Release Helm: $RELEASE"
ok "Namespace K8s: $NAMESPACE"

# ── StorageClass ──────────────────────────────────────────────────────────────
step "Storage (cache histórico)"

echo "  StorageClasses disponíveis:"
kubectl get storageclass --no-headers 2>/dev/null | awk '{print "    - " $1}' || echo "    (sem acesso)"

ask "StorageClass para o cache (deixe em branco para emptyDir/sem persistência): "
read -r SC
if [[ -n "$SC" ]]; then
    PERSIST_ENABLED="true"
    ok "Cache persistente: $SC"
else
    PERSIST_ENABLED="false"
    warn "Sem persistência — histórico de health trend não sobrevive entre jobs"
fi

# ── Schedule ──────────────────────────────────────────────────────────────────
step "Agendamento"

ask "Schedule cron (padrão: 0 7 * * 1-5 = seg-sex às 07h): "
read -r SCHEDULE
SCHEDULE="${SCHEDULE:-0 7 * * 1-5}"
ok "Schedule: $SCHEDULE"

# ── E-mail ────────────────────────────────────────────────────────────────────
step "Notificação por e-mail"

ask "SMTP host (padrão: smtp.office365.com): "
read -r SMTP_HOST; SMTP_HOST="${SMTP_HOST:-smtp.office365.com}"

ask "SMTP porta (padrão: 587): "
read -r SMTP_PORT; SMTP_PORT="${SMTP_PORT:-587}"

ask "Usuário SMTP (e-mail de envio): "
read -r SMTP_USER

ask "Senha SMTP: "
read -rs SMTP_PASS; echo ""

ask "Destinatário(s) separados por vírgula: "
read -r EMAIL_TO

ask "CC (opcional): "
read -r EMAIL_CC

ok "E-mail configurado: $SMTP_USER → $EMAIL_TO"

# ── Teams ─────────────────────────────────────────────────────────────────────
step "Microsoft Teams webhook (opcional)"

ask "URL do webhook Teams (Enter para pular): "
read -r TEAMS_URL

if [[ -n "$TEAMS_URL" ]]; then
    ok "Teams configurado"
else
    warn "Teams não configurado — pode adicionar depois com configure-webhooks.sh"
fi

# ── kubeconfig externo (multi-cluster) ────────────────────────────────────────
step "Multi-cluster / kubeconfig externo"

ask "Montar kubeconfig externo para acessar outros clusters? [s/N]: "
read -r USE_KUBECONFIG
KUBECONFIG_SECRET=""
if [[ "$USE_KUBECONFIG" =~ ^[sS]$ ]]; then
    ask "Caminho do arquivo kubeconfig: "
    read -r KC_PATH
    if [[ -f "$KC_PATH" ]]; then
        KUBECONFIG_SECRET="${RELEASE}-kubeconfig"
        ok "kubeconfig será criado como Secret: $KUBECONFIG_SECRET"
    else
        err "Arquivo não encontrado: $KC_PATH"
        KC_PATH=""
    fi
fi

# ── OpenShift SCC ────────────────────────────────────────────────────────────
CREATE_SCC="false"
if [[ "$PLATFORM" == "openshift" ]]; then
    step "OpenShift — Security Context Constraints"
    ask "Criar SCC anyuid para o ServiceAccount? [S/n]: "
    read -r SCC_ANS
    [[ ! "$SCC_ANS" =~ ^[nN]$ ]] && CREATE_SCC="true" && ok "SCC anyuid será criado"
fi

# ── Revisão ───────────────────────────────────────────────────────────────────
step "Revisão"
echo ""
echo -e "  ${BOLD}Cliente:${NC}        $CLIENT_NAME"
echo -e "  ${BOLD}Plataforma:${NC}     $PLATFORM"
echo -e "  ${BOLD}Namespace:${NC}      $NAMESPACE"
echo -e "  ${BOLD}Release:${NC}        $RELEASE"
echo -e "  ${BOLD}Schedule:${NC}       $SCHEDULE"
echo -e "  ${BOLD}SMTP:${NC}           $SMTP_USER → $EMAIL_TO"
echo -e "  ${BOLD}Teams:${NC}          ${TEAMS_URL:-não configurado}"
echo -e "  ${BOLD}Persistência:${NC}   ${SC:-emptyDir}"
echo -e "  ${BOLD}kubeconfig ext:${NC} ${KC_PATH:-não}"
echo ""
ask "Confirma instalação? [s/N]: "
read -r CONFIRM
[[ ! "$CONFIRM" =~ ^[sS]$ ]] && echo "Cancelado." && exit 0

# ── Instalação ────────────────────────────────────────────────────────────────
step "Instalando"

# Namespace
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
ok "Namespace: $NAMESPACE"

# kubeconfig externo → Secret
EXTRA_VOLUMES=""; EXTRA_MOUNTS=""; EXTRA_ENV=""
if [[ -n "${KC_PATH:-}" && -f "$KC_PATH" ]]; then
    kubectl create secret generic "$KUBECONFIG_SECRET" \
        --from-file=config="$KC_PATH" \
        -n "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
    ok "Secret kubeconfig: $KUBECONFIG_SECRET"

    EXTRA_VOLUMES=$(cat << YAML
- name: kubeconfig-ext
  secret:
    secretName: ${KUBECONFIG_SECRET}
YAML
)
    EXTRA_MOUNTS=$(cat << YAML
- name: kubeconfig-ext
  mountPath: /kubeconfig
  readOnly: true
YAML
)
    EXTRA_ENV=$(cat << YAML
- name: KUBECONFIG
  value: /kubeconfig/config
YAML
)
fi

# Gera values-<cliente>.yaml
VALUES_FILE="$VALUES_DIR/values-${CLIENT_NAME}.yaml"
cat > "$VALUES_FILE" << YAML
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Arquivo: values/values-${CLIENT_NAME}.yaml
# Desc:    Configuração do K8s Status Report para: ${CLIENT_NAME}
# Plataforma detectada: ${PLATFORM}
# =============================================================================

image:
  repository: ghcr.io/drmsantos/status-report
  tag: ""
  pullPolicy: IfNotPresent

cronjob:
  schedule: "${SCHEDULE}"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  activeDeadlineSeconds: 600
  restartPolicy: OnFailure

config:
  clusters: ""          # vazio = auto-discovery via kubeconfig
  contexts: ""
  outputDir: /data/reports
  cacheDir:  /data/cache

smtp:
  host:      "${SMTP_HOST}"
  port:      "${SMTP_PORT}"
  user:      "${SMTP_USER}"
  password:  "${SMTP_PASS}"
  fromName:  "K8s Status Report"
  fromEmail: "${SMTP_USER}"

email:
  to:  "${EMAIL_TO}"
  cc:  "${EMAIL_CC}"
  bcc: ""
  replyTo: ""

teams:
  webhookUrl: "${TEAMS_URL}"

slack:
  webhookUrl: ""
  channel:    ""

persistence:
  enabled:      ${PERSIST_ENABLED}
  storageClass: "${SC:-}"
  accessMode:   ReadWriteOnce
  size:         200Mi
  mountPath:    /data/cache

openshift:
  createSCC: ${CREATE_SCC}

rbac:
  create:      true
  clusterRole: true

serviceAccount:
  create: true

resources:
  requests:
    cpu:    100m
    memory: 256Mi
  limits:
    cpu:    500m
    memory: 512Mi

podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000

securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: false
  capabilities:
    drop: [ALL]

extraVolumes: ${EXTRA_VOLUMES:-[]}
extraVolumeMounts: ${EXTRA_MOUNTS:-[]}
extraEnv: ${EXTRA_ENV:-[]}
YAML

ok "Values gerado: $VALUES_FILE"

# Helm install/upgrade
helm upgrade --install "$RELEASE" "$CHART_DIR" \
    -n "$NAMESPACE" \
    -f "$VALUES_FILE" \

ok "Helm: $RELEASE instalado"

# ── Validação ─────────────────────────────────────────────────────────────────
step "Validação — disparando job de teste"

TEST_JOB="${RELEASE}-install-test"
kubectl delete job "$TEST_JOB" -n "$NAMESPACE" --ignore-not-found &>/dev/null || true
kubectl create job --from="cronjob/${RELEASE}" "$TEST_JOB" -n "$NAMESPACE"

echo -n "  Aguardando conclusão (máx 120s)"
for i in $(seq 1 24); do
    sleep 5; echo -n "."
    PHASE=$(kubectl get pod -n "$NAMESPACE" -l "job-name=${TEST_JOB}" \
            -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "")
    [[ "$PHASE" == "Succeeded" || "$PHASE" == "Failed" ]] && break
done
echo ""

kubectl logs -n "$NAMESPACE" -l "job-name=${TEST_JOB}" --tail=8 2>/dev/null || true

PHASE=$(kubectl get pod -n "$NAMESPACE" -l "job-name=${TEST_JOB}" \
        -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Unknown")

echo ""
if [[ "$PHASE" == "Succeeded" ]]; then
    ok "Job de teste: Succeeded"
    echo ""
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════╗"
    echo    "║  Instalação concluída com sucesso!                       ║"
    echo -e "╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  Namespace:   ${CYAN}$NAMESPACE${NC}"
    echo -e "  Release:     ${CYAN}$RELEASE${NC}"
    echo -e "  Values:      ${CYAN}$VALUES_FILE${NC}"
    echo -e "  Próxima exec: ${CYAN}$SCHEDULE${NC}"
    echo ""
    echo -e "  Para reconfigurar webhooks:"
    echo -e "  ${CYAN}NAMESPACE=$NAMESPACE bash scripts/configure-webhooks.sh${NC}"
    echo ""
    echo -e "  Para desinstalar:"
    echo -e "  ${CYAN}bash install.sh --uninstall${NC}"
else
    warn "Job de teste: $PHASE — verifique os logs acima"
    echo ""
    echo -e "  Para investigar:"
    echo -e "  ${CYAN}kubectl logs -n $NAMESPACE -l job-name=${TEST_JOB} --tail=50${NC}"
fi
