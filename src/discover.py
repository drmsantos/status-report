#!/usr/bin/env python3
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versão:  1.0.0
# Arquivo: discover.py
# Desc:    Auto-discovery de clusters Kubernetes/OpenShift via kubeconfig
# =============================================================================

import subprocess
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT  = int(os.getenv("CLUSTER_CONNECT_TIMEOUT", "5"))
EXCLUDE_CLUSTERS = {
    c.strip() for c in os.getenv("EXCLUDE_CLUSTERS", "").split(",") if c.strip()
}


@dataclass
class ClusterInfo:
    name: str
    context: str
    platform: str   # "kubernetes" | "openshift"
    server: str
    reachable: bool


def _kubectl(args: list, context: Optional[str] = None, timeout: int = 10) -> tuple[bool, str]:
    cmd = ["kubectl"]
    if context:
        cmd += ["--context", context]
    cmd += args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, "kubectl not found"


def _detect_platform(context: str) -> str:
    """Detecta se o cluster é OpenShift ou Kubernetes vanilla/RKE2."""
    ok, out = _kubectl(["api-resources", "--api-group=route.openshift.io",
                        "--no-headers"], context=context, timeout=CONNECT_TIMEOUT)
    if ok and "route" in out.lower():
        return "openshift"
    return "kubernetes"


def _get_server(context: str) -> str:
    """Retorna a URL da API do cluster para o contexto dado."""
    ok, out = _kubectl(
        ["config", "view", "--minify", "--output",
         "jsonpath={.clusters[0].cluster.server}"],
        context=context, timeout=5
    )
    return out.strip() if ok else "?"


def list_contexts() -> list[str]:
    """Lista todos os contextos disponíveis no kubeconfig."""
    ok, out = _kubectl(["config", "get-contexts", "-o", "name"], timeout=5)
    if not ok:
        return []
    return [c.strip() for c in out.splitlines() if c.strip()]


def discover_clusters(kubeconfig: Optional[str] = None) -> list[ClusterInfo]:
    """
    Descobre e testa todos os clusters disponíveis no kubeconfig.

    Ordem de prioridade:
      1. KUBECONFIG env / parâmetro kubeconfig
      2. K8S_CLUSTERS env (lista manual — compatibilidade retroativa)
      3. Contexto atual (in-cluster / default)
    """
    if kubeconfig:
        os.environ["KUBECONFIG"] = kubeconfig

    # Compatibilidade retroativa: se K8S_CLUSTERS definido, usa ele
    clusters_env = os.getenv("K8S_CLUSTERS", "").strip()
    contexts_env = os.getenv("K8S_CONTEXTS", "").strip()
    if clusters_env:
        logger.info("Auto-discovery: usando K8S_CLUSTERS definido manualmente")
        clusters_list = [c.strip() for c in clusters_env.split(",") if c.strip()]
        contexts_list = [c.strip() for c in contexts_env.split(",") if c.strip()] if contexts_env else []
        pairs = []
        for i, name in enumerate(clusters_list):
            ctx = contexts_list[i] if i < len(contexts_list) else None
            pairs.append((name, ctx))
        return _probe_pairs(pairs)

    # Auto-discovery via kubeconfig
    contexts = list_contexts()
    if not contexts:
        # Sem kubeconfig — tenta in-cluster com nome do pod/namespace
        cluster_name = os.getenv("K8S_CLUSTER_NAME",
                       os.getenv("MY_NODE_NAME", "default"))
        logger.info(f"Auto-discovery: sem contextos, usando in-cluster ({cluster_name})")
        return _probe_pairs([(cluster_name, None)])

    logger.info(f"Auto-discovery: {len(contexts)} contexto(s) encontrado(s): {contexts}")
    pairs = [(ctx, ctx) for ctx in contexts if ctx not in EXCLUDE_CLUSTERS]
    return _probe_pairs(pairs)


def _probe_pairs(pairs: list[tuple[str, Optional[str]]]) -> list[ClusterInfo]:
    """Testa conectividade e detecta plataforma de cada par (nome, contexto)."""
    results = []
    for name, context in pairs:
        logger.info(f"  Testando: {name} (ctx={context or 'current'}) ...")
        ok, _ = _kubectl(["version", "--short"], context=context, timeout=CONNECT_TIMEOUT)
        if not ok:
            # fallback: tenta sem --short (K8s >= 1.28 removeu a flag)
            ok, _ = _kubectl(["version"], context=context, timeout=CONNECT_TIMEOUT)

        platform = _detect_platform(context) if ok else "unknown"
        server   = _get_server(context) if ok else "?"

        status = "OK" if ok else "UNREACHABLE"
        logger.info(f"    → {status} | plataforma: {platform} | api: {server}")

        results.append(ClusterInfo(
            name=name,
            context=context,
            platform=platform,
            server=server,
            reachable=ok,
        ))

    reachable = [c for c in results if c.reachable]
    unreachable = [c for c in results if not c.reachable]
    if unreachable:
        logger.warning(f"Auto-discovery: {len(unreachable)} cluster(s) inacessível(is): "
                       f"{[c.name for c in unreachable]}")
    logger.info(f"Auto-discovery: {len(reachable)} cluster(s) disponível(is) para coleta")
    return results
