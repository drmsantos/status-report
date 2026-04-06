# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versão:  2.0.0
# Arquivo: Makefile
# Desc:    Targets de conveniência para build, push, deploy e testes
# =============================================================================

REGISTRY        := ghcr.io/drmsantos
IMAGE_NAME      := status-report
VERSION         ?= 2.0.0
IMAGE_FULL      := $(REGISTRY)/$(IMAGE_NAME):$(VERSION)
IMAGE_LATEST    := $(REGISTRY)/$(IMAGE_NAME):latest

HELM_CHART      := ./helm/status-report
RELEASE_NAME    := status-report
NAMESPACE       ?= monitoring

# Cluster alvo: rkeopl | openshift | rancher-local
CLUSTER         ?= rkeopl
VALUES_FILE     := values-$(CLUSTER).yaml

.PHONY: help build push build-push lint template \
        install upgrade uninstall test-run logs jobs \
        secret-smtp secret-show clean

# ── Help ──────────────────────────────────────────────────────────────────────
help: ## Mostra esta ajuda
	@echo ""
	@echo "  K8s Status Report — OpenLabs DevOps"
	@echo "  Uso: make <target> [CLUSTER=rkeopl|openshift|rancher-local] [VERSION=x.y.z]"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ── Docker ────────────────────────────────────────────────────────────────────
build: ## Build da imagem Docker local
	docker build \
	  --build-arg KUBECTL_VERSION=v1.29.3 \
	  -t $(IMAGE_FULL) \
	  -t $(IMAGE_LATEST) \
	  .

push: ## Push da imagem para ghcr.io (requer docker login)
	docker push $(IMAGE_FULL)
	docker push $(IMAGE_LATEST)

build-push: build push ## Build + Push em sequência

# Build multi-arch (requer buildx configurado)
build-multiarch: ## Build multi-arch linux/amd64,linux/arm64 e push
	docker buildx build \
	  --platform linux/amd64,linux/arm64 \
	  --build-arg KUBECTL_VERSION=v1.29.3 \
	  -t $(IMAGE_FULL) \
	  -t $(IMAGE_LATEST) \
	  --push \
	  .

# ── Helm ──────────────────────────────────────────────────────────────────────
lint: ## Helm lint do chart
	helm lint $(HELM_CHART) --strict
	helm lint $(HELM_CHART) -f $(VALUES_FILE) --strict

template: ## Renderiza os templates Helm (dry-run)
	helm template $(RELEASE_NAME) $(HELM_CHART) \
	  -f $(VALUES_FILE) \
	  --namespace $(NAMESPACE) \
	  --debug

install: ## Instala o chart no cluster (CLUSTER=rkeopl)
	@echo "→ Instalando no cluster: $(CLUSTER) | namespace: $(NAMESPACE)"
	helm install $(RELEASE_NAME) $(HELM_CHART) \
	  -f $(VALUES_FILE) \
	  --namespace $(NAMESPACE) \
	  --create-namespace \
	  --atomic \
	  --timeout 120s

upgrade: ## Atualiza o release existente
	@echo "→ Atualizando release: $(RELEASE_NAME) | cluster: $(CLUSTER)"
	helm upgrade $(RELEASE_NAME) $(HELM_CHART) \
	  -f $(VALUES_FILE) \
	  --namespace $(NAMESPACE) \
	  --atomic \
	  --timeout 120s

uninstall: ## Remove o release do cluster
	helm uninstall $(RELEASE_NAME) --namespace $(NAMESPACE)

diff: ## Helm diff (requer plugin helm-diff: helm plugin install https://github.com/databus23/helm-diff)
	helm diff upgrade $(RELEASE_NAME) $(HELM_CHART) \
	  -f $(VALUES_FILE) \
	  --namespace $(NAMESPACE)

# ── Operações no cluster ──────────────────────────────────────────────────────
test-run: ## Dispara execução manual do CronJob para teste imediato
	kubectl create job \
	  --from=cronjob/$(RELEASE_NAME) \
	  $(RELEASE_NAME)-manual-$$(date +%s) \
	  --namespace $(NAMESPACE)
	@echo "→ Job criado. Acompanhe com: make logs"

logs: ## Exibe logs do último pod executado
	kubectl logs \
	  -l app.kubernetes.io/name=$(IMAGE_NAME) \
	  --namespace $(NAMESPACE) \
	  --tail=200 \
	  --prefix

logs-follow: ## Streaming de logs em tempo real
	kubectl logs \
	  -l app.kubernetes.io/name=$(IMAGE_NAME) \
	  --namespace $(NAMESPACE) \
	  -f

jobs: ## Lista histórico de jobs
	kubectl get jobs \
	  -l app.kubernetes.io/instance=$(RELEASE_NAME) \
	  --namespace $(NAMESPACE) \
	  --sort-by=.metadata.creationTimestamp

describe-cronjob: ## Describe do CronJob
	kubectl describe cronjob/$(RELEASE_NAME) --namespace $(NAMESPACE)

# ── Secrets ───────────────────────────────────────────────────────────────────
# Uso: make secret-smtp SMTP_USER=user@dom.com.br SMTP_PASSWORD=senha
secret-smtp: ## Cria Secret SMTP manualmente (SMTP_USER e SMTP_PASSWORD obrigatórios)
ifndef SMTP_USER
	$(error SMTP_USER não definido. Uso: make secret-smtp SMTP_USER=u@d.com SMTP_PASSWORD=pass)
endif
ifndef SMTP_PASSWORD
	$(error SMTP_PASSWORD não definido.)
endif
	kubectl create secret generic $(RELEASE_NAME)-smtp \
	  --from-literal=smtp-user=$(SMTP_USER) \
	  --from-literal=smtp-password=$(SMTP_PASSWORD) \
	  --namespace $(NAMESPACE) \
	  --dry-run=client -o yaml | kubectl apply -f -
	@echo "→ Secret '$(RELEASE_NAME)-smtp' criado/atualizado no namespace $(NAMESPACE)"

# Uso: make secret-webhooks TEAMS_URL=https://... SLACK_URL=https://...
secret-webhooks: ## Cria Secret de webhooks (TEAMS_URL e/ou SLACK_URL)
	kubectl create secret generic $(RELEASE_NAME)-webhooks \
	  --from-literal=teams-webhook-url=$(TEAMS_URL) \
	  --from-literal=slack-webhook-url=$(SLACK_URL) \
	  --namespace $(NAMESPACE) \
	  --dry-run=client -o yaml | kubectl apply -f -
	@echo "→ Secret '$(RELEASE_NAME)-webhooks' criado/atualizado"

secret-show: ## Exibe os Secrets criados (decodificados)
	@echo "=== SMTP Secret ==="
	@kubectl get secret $(RELEASE_NAME)-smtp \
	  --namespace $(NAMESPACE) \
	  -o jsonpath='{.data.smtp-user}' 2>/dev/null | base64 -d && echo
	@echo "=== Webhooks Secret ==="
	@kubectl get secret $(RELEASE_NAME)-webhooks \
	  --namespace $(NAMESPACE) \
	  -o jsonpath='{.data.teams-webhook-url}' 2>/dev/null | base64 -d && echo

# ── Utilitários ───────────────────────────────────────────────────────────────
clean: ## Remove imagens Docker locais
	docker rmi $(IMAGE_FULL) $(IMAGE_LATEST) 2>/dev/null || true

package: ## Empacota o Helm chart em .tgz
	helm package $(HELM_CHART) --destination ./dist/

.env.example:
	@cp .env.example .env 2>/dev/null || true
