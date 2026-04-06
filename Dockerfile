# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versão:  2.0.0
# Arquivo: Dockerfile
# Desc:    Imagem do K8s Status Report — Python 3.12 + kubectl
# =============================================================================

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY src/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: kubectl downloader ───────────────────────────────────────────────
FROM curlimages/curl:latest AS kubectl-dl

ARG KUBECTL_VERSION=v1.29.3
RUN curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
      -o /tmp/kubectl && chmod +x /tmp/kubectl


# ── Stage 3: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

LABEL org.opencontainers.image.title="status-report"
LABEL org.opencontainers.image.description="Kubernetes Status Report — OpenLabs DevOps"
LABEL org.opencontainers.image.authors="diego-f-santos@openlabs.com.br"
LABEL org.opencontainers.image.source="https://github.com/drmsantos/status-report"

# kubectl
COPY --from=kubectl-dl /tmp/kubectl /usr/local/bin/kubectl

# Python packages
COPY --from=builder /install /usr/local

# App
WORKDIR /app
COPY src/ .

# Permissão de execução no entrypoint
RUN chmod +x /app/entrypoint.sh

# Diretórios de runtime
RUN mkdir -p /data/reports /data/cache && \
    chmod -R 777 /data

# Usuário não-root (UID 1000 para compatibilidade com SCC OpenShift)
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/sh -d /app appuser && \
    chown -R appuser:appgroup /app /data

USER 1000

ENV PYTHONUNBUFFERED=1 \
    OUTPUT_DIR=/data/reports \
    CACHE_DIR=/data/cache

ENTRYPOINT ["/app/entrypoint.sh"]
