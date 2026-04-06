#!/bin/sh
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versão:  2.0.0
# Arquivo: src/entrypoint.sh
# Desc:    Entrypoint do container — valida env, prepara dirs e executa main.py
# =============================================================================

set -e

# ── Cores para log ────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; RESET='\033[0m'

log()  { echo "${CYAN}[entrypoint]${RESET} $*"; }
warn() { echo "${YELLOW}[entrypoint] WARN:${RESET} $*"; }
err()  { echo "${RED}[entrypoint] ERROR:${RESET} $*" >&2; }
ok()   { echo "${GREEN}[entrypoint] OK:${RESET} $*"; }

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo "  ☸  K8s Status Report v2.0.0"
echo "  OpenLabs — DevOps | Infra"
echo "  github.com/drmsantos/status-report"
echo ""

# ── Verificação do kubectl ────────────────────────────────────────────────────
log "Verificando kubectl..."
if ! command -v kubectl >/dev/null 2>&1; then
  err "kubectl não encontrado no PATH"
  exit 1
fi
KUBECTL_VER=$(kubectl version --client --short 2>/dev/null || kubectl version --client 2>/dev/null | head -1)
ok "kubectl: $KUBECTL_VER"

# ── Verifica acesso ao cluster ────────────────────────────────────────────────
log "Testando acesso ao cluster..."
if kubectl cluster-info --request-timeout=10s >/dev/null 2>&1; then
  ok "Cluster acessível"
else
  warn "Não foi possível confirmar acesso ao cluster — continuando mesmo assim"
  warn "O script principal vai tentar coletar e reportar erros individualmente"
fi

# ── Verifica variáveis obrigatórias ──────────────────────────────────────────
ERRORS=0

if [ -z "$SMTP_USER" ]; then
  warn "SMTP_USER não definido — e-mail não será enviado"
fi

if [ -z "$EMAIL_TO" ] && [ -z "$TEAMS_WEBHOOK_URL" ] && [ -z "$SLACK_WEBHOOK_URL" ]; then
  warn "Nenhum destino de notificação configurado (EMAIL_TO, TEAMS_WEBHOOK_URL, SLACK_WEBHOOK_URL)"
  warn "O relatório PDF será gerado mas não enviado"
fi

# ── Prepara diretórios ────────────────────────────────────────────────────────
OUTPUT_DIR="${OUTPUT_DIR:-/data/reports}"
CACHE_DIR="${CACHE_DIR:-/data/cache}"

log "Preparando diretórios..."
mkdir -p "$OUTPUT_DIR" "$CACHE_DIR"
ok "OUTPUT_DIR=$OUTPUT_DIR"
ok "CACHE_DIR=$CACHE_DIR"

# ── Resumo da configuração ────────────────────────────────────────────────────
log "Configuração:"
echo "  Clusters  : ${K8S_CLUSTERS:-default}"
echo "  Contexts  : ${K8S_CONTEXTS:-(current)}"
echo "  E-mail    : ${EMAIL_TO:-(não configurado)}"
echo "  Teams     : $([ -n "$TEAMS_WEBHOOK_URL" ] && echo 'configurado' || echo 'não configurado')"
echo "  Slack     : $([ -n "$SLACK_WEBHOOK_URL" ] && echo 'configurado' || echo 'não configurado')"
echo ""

# ── Trap para SIGTERM (graceful shutdown no watch mode) ───────────────────────
trap 'log "Recebido SIGTERM — encerrando..."; exit 0' TERM INT

# ── Executa o main.py passando todos os argumentos recebidos ─────────────────
log "Iniciando main.py..."
exec python /app/main.py "$@"
