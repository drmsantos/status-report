#!/bin/bash
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Arquivo: configure-webhooks.sh
# Desc:    Configura webhooks de notificação do K8s Status Report
# =============================================================================

set -e

NAMESPACE="${NAMESPACE:-status-report}"
SECRET_NAME="status-report-webhooks"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║     K8s Status Report — Configuração de Webhooks     ║"
echo "║     OpenLabs DevOps | Infra                          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

if ! command -v kubectl &>/dev/null; then
    echo -e "${RED}✗ kubectl não encontrado${NC}"; exit 1
fi

if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    echo -e "${RED}✗ Namespace '$NAMESPACE' não encontrado${NC}"; exit 1
fi

CURRENT_TEAMS=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" \
    -o jsonpath='{.data.teams-webhook-url}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
CURRENT_SLACK=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" \
    -o jsonpath='{.data.slack-webhook-url}' 2>/dev/null | base64 -d 2>/dev/null || echo "")

echo -e "Namespace: ${CYAN}$NAMESPACE${NC}\n"

# ── Teams ──────────────────────────────────────────────────────────────────
echo -e "${YELLOW}▶ Microsoft Teams${NC}"
if [ -n "$CURRENT_TEAMS" ] && [[ "$CURRENT_TEAMS" == https://out\* ]]; then
    echo -e "  Atual: ${GREEN}${CURRENT_TEAMS:0:50}...${NC}"
else
    echo -e "  Atual: ${RED}não configurado${NC}"
fi

read -rp "  Configurar Teams webhook? [s/N] " CONF_TEAMS
TEAMS_CONFIGURED=false
if [[ "$CONF_TEAMS" =~ ^[sS]$ ]]; then
    while true; do
        read -rp "  Cole a URL do webhook: " TEAMS_URL
        TEAMS_URL=$(echo "$TEAMS_URL" | tr -d '[:space:]')
        if [[ "$TEAMS_URL" =~ ^https://(outlook\.office\.com|outlook\.office365\.com|.*\.webhook\.office\.com)/ ]]; then
            echo -e "  ${GREEN}✓ URL válida${NC}"
            TEAMS_B64=$(echo -n "$TEAMS_URL" | base64 | tr -d '\n')
            kubectl patch secret "$SECRET_NAME" -n "$NAMESPACE" \
                --type='json' \
                -p="[{\"op\":\"replace\",\"path\":\"/data/teams-webhook-url\",\"value\":\"$TEAMS_B64\"}]" &>/dev/null
            echo -e "  ${GREEN}✓ Teams webhook salvo${NC}"
            TEAMS_CONFIGURED=true
            break
        else
            echo -e "  ${RED}✗ URL inválida${NC}"
            read -rp "  Tentar novamente? [s/N] " RETRY
            [[ "$RETRY" =~ ^[sS]$ ]] || break
        fi
    done
fi

echo ""

# ── Slack ──────────────────────────────────────────────────────────────────
echo -e "${YELLOW}▶ Slack${NC}"
if [ -n "$CURRENT_SLACK" ] && [[ "$CURRENT_SLACK" == https://hooks.slack\* ]]; then
    echo -e "  Atual: ${GREEN}${CURRENT_SLACK:0:50}...${NC}"
else
    echo -e "  Atual: ${RED}não configurado${NC}"
fi

read -rp "  Configurar Slack webhook? [s/N] " CONF_SLACK
SLACK_CONFIGURED=false
if [[ "$CONF_SLACK" =~ ^[sS]$ ]]; then
    while true; do
        read -rp "  Cole a URL do webhook: " SLACK_URL
        SLACK_URL=$(echo "$SLACK_URL" | tr -d '[:space:]')
        if [[ "$SLACK_URL" =~ ^https://hooks\.slack\.com/services/ ]]; then
            echo -e "  ${GREEN}✓ URL válida${NC}"
            SLACK_B64=$(echo -n "$SLACK_URL" | base64 | tr -d '\n')
            kubectl patch secret "$SECRET_NAME" -n "$NAMESPACE" \
                --type='json' \
                -p="[{\"op\":\"replace\",\"path\":\"/data/slack-webhook-url\",\"value\":\"$SLACK_B64\"}]" &>/dev/null
            echo -e "  ${GREEN}✓ Slack webhook salvo${NC}"
            SLACK_CONFIGURED=true
            break
        else
            echo -e "  ${RED}✗ URL inválida${NC}"
            read -rp "  Tentar novamente? [s/N] " RETRY
            [[ "$RETRY" =~ ^[sS]$ ]] || break
        fi
    done
fi

echo ""

# ── Teste ──────────────────────────────────────────────────────────────────
if [ "$TEAMS_CONFIGURED" = true ] || [ "$SLACK_CONFIGURED" = true ]; then
    echo -e "${YELLOW}▶ Teste de notificação${NC}"
    read -rp "  Disparar job de teste agora? [s/N] " RUN_TEST
    if [[ "$RUN_TEST" =~ ^[sS]$ ]]; then
        JOB_NAME="status-report-webhook-test"
        kubectl delete job "$JOB_NAME" -n "$NAMESPACE" &>/dev/null || true
        kubectl create job --from=cronjob/status-report "$JOB_NAME" -n "$NAMESPACE"
        echo -e "  Job criado. Aguardando 60s..."
        sleep 60
        kubectl logs -n "$NAMESPACE" -l "job-name=$JOB_NAME" --tail=5 2>/dev/null | \
            grep -iE "teams|slack|notif|enviado" || echo "  Verifique os logs manualmente."
        echo -e "  ${GREEN}✓ Verifique seu canal${NC}"
    fi
fi

echo ""
echo -e "${GREEN}✓ Configuração concluída!${NC}"
echo -e "  Para reconfigurar: ${CYAN}NAMESPACE=<ns> bash configure-webhooks.sh${NC}\n"
