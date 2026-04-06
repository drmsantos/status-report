# ☸ status-report

> **Kubernetes Status Report** — coleta automática de dados do cluster, geração de PDF profissional e envio por e-mail (Office 365), Microsoft Teams e Slack. Executado como **CronJob nativo** no próprio cluster, deployado via **Helm Chart**, compatível com **Rancher RKE2**, **OpenShift 4.x** e qualquer cluster Kubernetes.

**Autor:** Diego Regis M. F. dos Santos  
**E-mail:** diego-f-santos@openlabs.com.br  
**Time:** OpenLabs — DevOps | Infra  
**Versão:** 2.0.0

---

## Conteúdo do Relatório

| Seção | O que coleta |
|---|---|
| **Resumo Executivo** | Health Score, 12 KPIs, alertas por severidade, comparativo histórico |
| **Distribuição** | Gráficos de pizza (pods por namespace / por status), top pods CPU/Mem |
| **Nodes** | Status, versão, CPU/Mem real (`kubectl top`) com % colorida |
| **Workloads** | Deployments, StatefulSets, DaemonSets, CronJobs, Jobs |
| **Pods** | Problemas em destaque, CrashLoop, OOMKilled, high restarts |
| **Rede / Storage** | PVCs, Ingresses, Services LB/NodePort, HPAs |
| **Events** | Warning events recentes com contagem |

---

## Pré-requisitos

- Helm 3.x
- `kubectl` configurado com acesso ao cluster alvo
- Imagem disponível em `ghcr.io/drmsantos/status-report:2.0.0`  
  *(ou build local — veja seção Docker abaixo)*

---

## Instalação rápida

### 1. Criar o Secret com as credenciais SMTP

```bash
kubectl create namespace monitoring

kubectl create secret generic status-report-smtp \
  --from-literal=smtp-user=seu_usuario@dominio.com.br \
  --from-literal=smtp-password=SuaSenhaOuAppPassword \
  -n monitoring
```

> **Office 365:** se MFA estiver habilitado, crie um **App Password** em  
> https://mysignins.microsoft.com/security-info

### 2. Helm install

```bash
# RKE2 / Rancher
helm install status-report ./helm/status-report \
  -f values-rkeopl.yaml \
  --namespace monitoring \
  --set smtp.existingSecret=status-report-smtp \
  --set email.to="ops@openlabs.com.br,gestor@openlabs.com.br" \
  --set teams.webhookUrl="https://openlabs.webhook.office.com/webhookb2/..."

# OpenShift 4.x
helm install status-report ./helm/status-report \
  -f values-openshift.yaml \
  --namespace monitoring \
  --set smtp.existingSecret=status-report-smtp \
  --set openshift.createSCC=true \
  --set email.to="ops@openlabs.com.br"

# Rancher pessoal
helm install status-report ./helm/status-report \
  -f values-rancher-local.yaml \
  --namespace monitoring \
  --set smtp.existingSecret=status-report-smtp
```

### 3. Testar imediatamente

```bash
make test-run CLUSTER=rkeopl
# ou manualmente:
kubectl create job --from=cronjob/status-report \
  status-report-test-$(date +%s) -n monitoring
```

### 4. Acompanhar logs

```bash
make logs CLUSTER=rkeopl
# ou:
kubectl logs -l app.kubernetes.io/name=status-report \
  -n monitoring --tail=200 -f
```

---

## Makefile — comandos disponíveis

```
make help                           # lista todos os targets

# Docker
make build                          # build local da imagem
make push                           # push para ghcr.io
make build-push                     # build + push
make build-multiarch                # build linux/amd64 + arm64

# Helm
make lint                           # helm lint
make template CLUSTER=rkeopl        # dry-run dos templates
make install CLUSTER=rkeopl         # helm install
make upgrade CLUSTER=rkeopl         # helm upgrade
make uninstall                      # remove o release
make diff CLUSTER=rkeopl            # diff com release atual

# Operações no cluster
make test-run CLUSTER=rkeopl        # dispara job manual
make logs CLUSTER=rkeopl            # logs do último pod
make logs-follow CLUSTER=rkeopl     # streaming de logs
make jobs CLUSTER=rkeopl            # histórico de jobs

# Secrets
make secret-smtp SMTP_USER=u@d.com SMTP_PASSWORD=pass
make secret-webhooks TEAMS_URL=https://... SLACK_URL=https://...
make secret-show
```

---

## Configuração completa (values.yaml)

### Agendamento

```yaml
cronjob:
  schedule: "0 7 * * 1-5"     # seg-sex 07h
  # schedule: "0 7,19 * * *"  # 2x ao dia
  # schedule: "0 */6 * * *"   # a cada 6h
  concurrencyPolicy: Forbid
  activeDeadlineSeconds: 600
```

### Múltiplos clusters

Para reportar **vários clusters no mesmo relatório**, cada cluster precisa de um kubeconfig acessível pelo pod. Use `extraVolumes` para montar um Secret com o kubeconfig externo:

```yaml
config:
  clusters: "rkeopl,openshift"
  contexts: "rkeopl-ctx,openshift-ctx"

extraVolumes:
  - name: kubeconfig-multi
    secret:
      secretName: kubeconfig-multi-cluster

extraVolumeMounts:
  - name: kubeconfig-multi
    mountPath: /home/appuser/.kube/config
    subPath: config

extraEnv:
  - name: KUBECONFIG
    value: /home/appuser/.kube/config
```

Criar o Secret com o kubeconfig merged:
```bash
kubectl create secret generic kubeconfig-multi-cluster \
  --from-file=config=$HOME/.kube/config-merged \
  -n monitoring
```

### Modo watch (alertas em tempo real)

Para rodar em loop contínuo dentro do pod em vez do CronJob:

```yaml
config:
  watchMode: true
  watchInterval: 10      # minutos
  alertOnly: true        # notifica só se houver problemas
```

> Com `watchMode: true` o CronJob ainda existe mas o container não termina — funciona como um Deployment.

### Notificações

```yaml
smtp:
  host:     "smtp.office365.com"
  port:     "587"
  fromName: "OpenLabs DevOps"
  existingSecret: "status-report-smtp"   # recomendado em prod

email:
  to: "ops@empresa.com.br,gestor@empresa.com.br"
  cc: "cco@empresa.com.br"

teams:
  webhookUrl: "https://openlabs.webhook.office.com/..."
  # ou: existingSecret: "meu-secret-teams"

slack:
  webhookUrl: "https://hooks.slack.com/services/..."
  channel:    "#devops-alerts"
```

### Persistência do histórico (comparativo diário)

```yaml
persistence:
  enabled:      true
  storageClass: "longhorn-1r"   # longhorn, nfs-sc, local-path
  size:         1Gi
```

Sem persistência o comparativo histórico não funciona entre execuções — o cache fica em `emptyDir` e é perdido quando o pod termina.

---

## CI/CD — GitHub Actions

O workflow `.github/workflows/docker-build.yml` faz:

| Trigger | Ação |
|---|---|
| Push em `main` | Build + push com tag `edge` + SHA |
| Tag `v2.1.0` | Push com tags `2.1.0`, `2.1`, `2`, `latest` |
| PR | Build apenas (sem push) |
| `workflow_dispatch` | Build + push manual |

```bash
# Criar nova release
git tag v2.1.0
git push origin v2.1.0
# → CI gera ghcr.io/drmsantos/status-report:2.1.0
```

Depois de publicada a imagem, atualizar o cluster:
```bash
make upgrade CLUSTER=rkeopl
# helm upgrade vai usar a nova image tag via Chart.appVersion
```

---

## RBAC — permissões necessárias

O chart cria um `ClusterRole` com permissões **somente leitura** nos seguintes recursos:

```
nodes, pods, namespaces, services, events
persistentvolumes, persistentvolumeclaims
deployments, statefulsets, daemonsets, replicasets
jobs, cronjobs
ingresses, ingressclasses
horizontalpodautoscalers
metrics.k8s.io/nodes, metrics.k8s.io/pods    ← kubectl top
route.openshift.io/routes                     ← OpenShift
```

---

## Estrutura do projeto

```
status-report/
├── src/
│   ├── models.py           # Dataclasses de todos os recursos
│   ├── collector.py        # kubectl + kubectl top + events
│   ├── pdf_generator.py    # Geração do PDF (reportlab)
│   ├── notifications.py    # E-mail, Teams, Slack
│   ├── cache.py            # Cache JSON local (histórico)
│   ├── main.py             # Entrypoint — orquestra tudo
│   └── requirements.txt
├── Dockerfile              # Multi-stage: Python 3.12 + kubectl
├── Makefile                # Targets de conveniência
├── values-rkeopl.yaml      # Overrides para RKE2 / Rancher
├── values-openshift.yaml   # Overrides para OpenShift 4.x
├── values-rancher-local.yaml
├── .github/workflows/
│   └── docker-build.yml    # CI/CD GitHub Actions
└── helm/status-report/
    ├── Chart.yaml
    ├── values.yaml         # Todos os parâmetros documentados
    └── templates/
        ├── cronjob.yaml
        ├── rbac.yaml
        ├── serviceaccount.yaml
        ├── configmap.yaml
        ├── secret.yaml
        ├── pvc.yaml
        ├── scc.yaml         # OpenShift SCC
        ├── NOTES.txt
        └── _helpers.tpl
```

---

## Troubleshooting

**Pod falha com `kubectl: command not found`**  
→ A imagem foi buildada sem o stage `kubectl-dl`. Rebuild com `make build`.

**`Error from server (Forbidden)` ao coletar recursos**  
→ O ClusterRoleBinding não foi criado. Verifique `rbac.create: true` nos values.

**OpenShift: `unable to validate against any security context constraint`**  
→ Ative `openshift.createSCC: true` no values e faça `helm upgrade`.

**E-mail não chega — Office 365**  
→ Verifique se o usuário tem "SMTP AUTH" habilitado no Exchange Admin Center  
→ Se MFA ativo, use App Password (não a senha principal)  
→ Teste: `make logs` e procure a linha `[smtplib]` no output

**Sem comparativo histórico**  
→ Ative `persistence.enabled: true` e escolha um `storageClass` disponível.

---

*OpenLabs — DevOps | Infra | diego-f-santos@openlabs.com.br*
