#!/usr/bin/env python3
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versão:  2.1.0
# Arquivo: cache.py
# Desc:    Cache JSON local para histórico comparativo entre reports
# Changelog v2.1.0:
#   - diff formatado com 1 casa decimal (fix 3.4000000000000057)
#   - load_previous corrigido: carrega ANTES de salvar o atual
#   - pvcs_pending_alert adicionado ao diff
#   - load_history retorna lista ordenada para sparkline
# =============================================================================
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from models import ClusterReport, HistoricalSnapshot

logger = logging.getLogger(__name__)
CACHE_DIR = Path(os.getenv("CACHE_DIR", "./cache"))


def _cache_file(cluster_name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = cluster_name.replace("/", "_").replace(":", "_")
    return CACHE_DIR / f"{safe}.json"


def load_previous(cluster_name: str) -> Optional[HistoricalSnapshot]:
    """Carrega o snapshot mais recente do cache (ANTES de salvar o atual)."""
    path = _cache_file(cluster_name)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            history = json.load(f)
        if not history:
            return None
        # Pega sempre o último snapshot salvo (que é o anterior ao atual)
        snap = history[-1]
        return HistoricalSnapshot(
            collected_at=snap["collected_at"],
            cluster_name=snap["cluster_name"],
            summary=snap["summary"],
        )
    except Exception as e:
        logger.warning(f"Erro ao carregar snapshot anterior: {e}")
        return None


def save_snapshot(report: ClusterReport):
    """Salva o sumário atual como snapshot histórico."""
    path = _cache_file(report.cluster_name)
    history = []
    if path.exists():
        try:
            with open(path) as f:
                history = json.load(f)
        except Exception as e:
            logger.warning(f"Erro ao carregar cache existente: {e}")

    snapshot = {
        "collected_at": report.collected_at,
        "cluster_name": report.cluster_name,
        "summary": report.summary,
    }
    history.append(snapshot)
    # Mantém últimos 7 snapshots para sparkline
    history = history[-7:]
    try:
        with open(path, "w") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        logger.info(f"Cache salvo: {path} ({len(history)} snapshots)")
    except Exception as e:
        logger.error(f"Erro ao salvar cache: {e}")


def load_history(cluster_name: str) -> list[HistoricalSnapshot]:
    """Carrega todos os snapshots do histórico (ordem cronológica)."""
    path = _cache_file(cluster_name)
    if not path.exists():
        return []
    try:
        with open(path) as f:
            history = json.load(f)
        return [
            HistoricalSnapshot(
                collected_at=s["collected_at"],
                cluster_name=s["cluster_name"],
                summary=s["summary"],
            )
            for s in history
        ]
    except Exception as e:
        logger.warning(f"Erro ao carregar histórico: {e}")
        return []


def diff_summary(current: dict, previous: dict) -> dict:
    """Retorna delta entre dois summaries para exibição comparativa."""
    numeric_keys = [
        "total_pods", "pods_running", "pods_pending", "pods_failed",
        "pods_crashloop", "pods_high_restarts", "nodes_not_ready",
        "deployments_degraded", "pvcs_lost", "pvcs_pending_alert",
        "warning_events", "health_score", "total_nodes", "total_deployments",
    ]
    delta = {}
    for k in numeric_keys:
        curr_val = current.get(k, 0)
        prev_val = previous.get(k, 0)
        raw_diff = curr_val - prev_val
        # Formata com 1 casa decimal para floats, inteiro para ints
        if isinstance(raw_diff, float) or isinstance(curr_val, float):
            diff = round(raw_diff, 1)
            curr_val = round(curr_val, 1) if isinstance(curr_val, float) else curr_val
            prev_val = round(prev_val, 1) if isinstance(prev_val, float) else prev_val
        else:
            diff = int(raw_diff)
        delta[k] = {
            "current":  curr_val,
            "previous": prev_val,
            "diff":     diff,
            "trend":    "up" if diff > 0 else ("down" if diff < 0 else "stable"),
        }
    return delta
