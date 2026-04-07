#!/usr/bin/env python3
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versão:  2.2.0
# Arquivo: main.py
# Desc:    Entrypoint v2 — Multi-cluster, Watch mode, Cache histórico
# Changelog v2.1.0:
#   - previous_summary passado para collect_all para health trend
# Changelog v2.2.0:
#   - auto-discovery via discover.py (substitui _parse_clusters)
#   - PVC Pending alert integrado no fluxo de notificações
# =============================================================================

import os
import sys
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path

from collector import collect_all
from discover import discover_clusters, ClusterInfo
from pdf_generator import generate_pdf
from notifications import load_config, send_email, send_teams, send_slack, should_alert
from cache import save_snapshot, load_previous, load_history, diff_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("k8s_report.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")


def _load_dotenv():
    for f in [".env", Path(__file__).parent / ".env"]:
        p = Path(f)
        if not p.exists():
            continue
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        break


def parse_args():
    p = argparse.ArgumentParser(
        description="K8s Status Report v2 — OpenLabs DevOps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  # Relatório único (cluster default)
  python main.py

  # Cluster específico
  python main.py --cluster rkeopl --context rkeopl-context

  # Múltiplos clusters em um só relatório
  python main.py --cluster rkeopl,openshift --context ctx1,ctx2

  # Apenas PDF, sem enviar
  python main.py --no-notify --output /tmp/report.pdf

  # Modo watch — coleta a cada 10 minutos, alerta se houver problemas
  python main.py --watch --interval 10

  # Watch com notificação imediata em Teams/Slack
  python main.py --watch --interval 5 --no-email

Variáveis de ambiente (.env):
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD
  SMTP_FROM_NAME / SMTP_FROM_EMAIL
  EMAIL_TO / EMAIL_CC / EMAIL_BCC / EMAIL_REPLY_TO
  TEAMS_WEBHOOK_URL
  SLACK_WEBHOOK_URL / SLACK_CHANNEL
  K8S_CLUSTERS          ex: rkeopl,openshift
  K8S_CONTEXTS          ex: ctx-rkeopl,ctx-ocp (mesma ordem)
  OUTPUT_DIR            ./reports
  CACHE_DIR             ./cache
  RESTART_THRESHOLD_APP ex: 5 (default)
  RESTART_THRESHOLD_SYS ex: 20 (default)
  PVC_PENDING_ALERT_DAYS ex: 1 (default)
        """
    )
    p.add_argument("--cluster",    default=None, help="Nome(s) do cluster separados por vírgula")
    p.add_argument("--context",    default=None, help="Contexto(s) kubectl separados por vírgula")
    p.add_argument("--output",     default=None, help="Caminho do PDF (single cluster)")
    p.add_argument("--no-notify",  action="store_true", help="Não envia nenhuma notificação")
    p.add_argument("--no-email",   action="store_true", help="Pula o e-mail")
    p.add_argument("--to",         action="append", default=[], help="Destinatário de e-mail (repetível)")
    p.add_argument("--watch",      action="store_true", help="Modo watch contínuo")
    p.add_argument("--interval",   type=int, default=15, help="Intervalo watch em minutos (default: 15)")
    p.add_argument("--alert-only", action="store_true", help="Watch: notifica apenas se houver problema")
    p.add_argument("--debug",      action="store_true")
    return p.parse_args()


def _parse_clusters(args) -> list[tuple[str, str | None]]:
    clusters_env = os.getenv("K8S_CLUSTERS", "")
    contexts_env = os.getenv("K8S_CONTEXTS", "")

    clusters = (args.cluster or clusters_env or os.getenv("K8S_CLUSTER_NAME", "default")).split(",")
    contexts = (args.context or contexts_env or "").split(",")

    result = []
    for i, c in enumerate(clusters):
        c = c.strip()
        ctx = contexts[i].strip() if i < len(contexts) and contexts[i].strip() else None
        result.append((c, ctx))
    return result


def run_once(args, cfg, output_dir: Path) -> list[Path]:
    discovered = discover_clusters()
    clusters = [(c.name, c.context) for c in discovered if c.reachable]
    generated_pdfs = []

    for cluster_name, context in clusters:
        logger.info(f"{'='*60}")
        logger.info(f"Cluster: {cluster_name} | Contexto: {context or 'current'}")

        # Carrega histórico antes de coletar
        previous = load_previous(cluster_name)
        previous_summary = previous.summary if previous else None

        # Coleta — passa previous_summary para health trend
        try:
            report = collect_all(
                cluster_name=cluster_name,
                context=context,
                previous_summary=previous_summary,
            )
        except Exception as e:
            logger.error(f"[{cluster_name}] Erro crítico na coleta: {e}")
            continue

        report.previous = previous

        # Delta
        delta = {}
        if previous:
            delta = diff_summary(report.summary, previous.summary)
            logger.info(f"[{cluster_name}] Health: {report.summary['health_score']}% "
                        f"(anterior: {previous.summary.get('health_score','?')}%)")
        else:
            logger.info(f"[{cluster_name}] Health: {report.summary['health_score']}% (sem histórico)")

        # Log PVCs Pending alert
        pvc_pending = report.summary.get("pvcs_pending_alert", 0)
        if pvc_pending > 0:
            pvc_list = report.summary.get("pvcs_pending_alert_list", [])
            for pvc in pvc_list:
                logger.warning(f"[{cluster_name}] PVC PENDING há {pvc['age']}: {pvc['ns']}/{pvc['name']}")

        # Salva cache
        save_snapshot(report)

        # Gera PDF
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if args.output and len(clusters) == 1:
            pdf_path = Path(args.output)
        else:
            safe_name = cluster_name.replace("/","_").replace(":","_")
            pdf_path = output_dir / f"k8s_status_{safe_name}_{ts}.pdf"

        try:
            history = load_history(cluster_name)
            generate_pdf(report, str(pdf_path), delta=delta, history=history)
            size_kb = pdf_path.stat().st_size / 1024
            logger.info(f"[{cluster_name}] PDF: {pdf_path} ({size_kb:.0f} KB)")
            generated_pdfs.append(pdf_path)
        except Exception as e:
            logger.error(f"[{cluster_name}] Erro ao gerar PDF: {e}")
            continue

        if args.no_notify:
            continue

        if args.alert_only:
            prev_sum = previous.summary if previous else None
            do_alert, reasons = should_alert(report, prev_sum)
            if not do_alert:
                logger.info(f"[{cluster_name}] Sem alertas — notificação pulada (--alert-only)")
                continue
            logger.info(f"[{cluster_name}] Alertas: {', '.join(reasons)}")

        # Notificações
        if not args.no_email and cfg.smtp_user and cfg.to:
            if args.to:
                cfg.to = args.to
            send_email(report, str(pdf_path), cfg, delta=delta)

        if cfg.teams_webhook:
            send_teams(report, cfg.teams_webhook)

        if cfg.slack_webhook:
            send_slack(report, cfg.slack_webhook, cfg.slack_channel)

    return generated_pdfs


def watch_mode(args, cfg, output_dir: Path):
    interval_sec = args.interval * 60
    logger.info(f"Modo WATCH ativo — intervalo: {args.interval} min | Ctrl+C para parar")

    iteration = 0
    while True:
        iteration += 1
        logger.info(f"[Watch] Iteração #{iteration}")
        try:
            run_once(args, cfg, output_dir)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"[Watch] Erro na iteração: {e}")

        logger.info(f"[Watch] Próxima coleta em {args.interval} min...")
        try:
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            logger.info("[Watch] Interrompido pelo usuário.")
            break


def main():
    args = parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    _load_dotenv()
    cfg = load_config()

    output_dir = Path(os.getenv("OUTPUT_DIR", "reports"))
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== K8s Status Report v2 — OpenLabs DevOps ===")

    if args.watch:
        try:
            watch_mode(args, cfg, output_dir)
        except KeyboardInterrupt:
            logger.info("Watch encerrado.")
    else:
        pdfs = run_once(args, cfg, output_dir)
        if pdfs:
            logger.info(f"=== Concluído — {len(pdfs)} relatório(s) gerado(s) ===")
            for p in pdfs:
                logger.info(f"  → {p}")
        else:
            logger.error("=== Nenhum relatório gerado ===")
            sys.exit(1)


if __name__ == "__main__":
    main()
