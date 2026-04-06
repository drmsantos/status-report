#!/usr/bin/env python3
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versão:  2.0.0
# Arquivo: cache.py
# Desc:    Cache JSON local para histórico comparativo entre reports
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


def save_snapshot(report: ClusterReport):
    """Salva o sumário atual como snapshot histórico."""
    path = _cache_file(report.cluster_name)

    # Carrega histórico existente (máx 7 snapshots)
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
    # Mantém últimos 7
    history = history[-7:]

    try:
        with open(path, "w") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        logger.info(f"Cache salvo: {path} ({len(history)} snapshots)")
    except Exception as e:
        logger.error(f"Erro ao salvar cache: {e}")


def load_previous(cluster_name: str) -> Optional[HistoricalSnapshot]:
    """Carrega o snapshot anterior (penúltimo) do cache."""
    path = _cache_file(cluster_name)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            history = json.load(f)
        if len(history) < 1:
            return None
        # O último é o atual (ainda não salvo), então pega o penúltimo
        # Mas como salvamos antes, pega o [-2] se existir, senão [-1]
        snap = history[-2] if len(history) >= 2 else history[-1]
        return HistoricalSnapshot(
            collected_at=snap["collected_at"],
            cluster_name=snap["cluster_name"],
            summary=snap["summary"],
        )
    except Exception as e:
        logger.warning(f"Erro ao carregar snapshot anterior: {e}")
        return None


def load_history(cluster_name: str) -> list[HistoricalSnapshot]:
    """Carrega todos os snapshots do histórico."""
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
        "deployments_degraded", "pvcs_lost", "warning_events",
        "health_score", "total_nodes", "total_deployments",
    ]
    delta = {}
    for k in numeric_keys:
        curr_val = current.get(k, 0)
        prev_val = previous.get(k, 0)
        diff = curr_val - prev_val
        delta[k] = {
            "current": curr_val,
            "previous": prev_val,
            "diff": diff,
            "trend": "up" if diff > 0 else ("down" if diff < 0 else "stable"),
        }
    return delta
