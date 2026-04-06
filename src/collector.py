#!/usr/bin/env python3
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versão:  2.0.0
# Arquivo: collector.py
# Desc:    Coleta completa de dados do cluster Kubernetes
# =============================================================================

import subprocess
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from models import (
    ClusterReport, NodeInfo, PodInfo, DeploymentInfo, StatefulSetInfo,
    DaemonSetInfo, CronJobInfo, JobInfo, PVCInfo, IngressInfo, ServiceInfo,
    HPAInfo, EventInfo, NamespaceInfo
)

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(args: list, context: Optional[str] = None, output_format: str = "json") -> tuple[bool, str]:
    cmd = ["kubectl"]
    if context:
        cmd += ["--context", context]
    cmd += args
    if output_format:
        cmd += ["-o", output_format]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if r.returncode == 0:
            return True, r.stdout
        logger.warning(f"kubectl {' '.join(args[:3])} → {r.stderr.strip()[:120]}")
        return False, r.stderr
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, "kubectl not found"


def _age(ts: str) -> str:
    try:
        created = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - created
        d, s = delta.days, delta.seconds
        if d > 0:   return f"{d}d"
        if s >= 3600: return f"{s//3600}h"
        return f"{s//60}m"
    except Exception:
        return "?"


def _cpu_to_m(cpu_str: str) -> int:
    """Converte string de CPU para millicores."""
    if not cpu_str or cpu_str in ("N/A", "?", "<unknown>"):
        return 0
    try:
        if cpu_str.endswith("m"):
            return int(cpu_str[:-1])
        return int(float(cpu_str) * 1000)
    except Exception:
        return 0


def _mem_to_mib(mem_str: str) -> int:
    """Converte string de memória para MiB."""
    if not mem_str or mem_str in ("N/A", "?", "<unknown>"):
        return 0
    try:
        mem_str = mem_str.strip()
        if mem_str.endswith("Ki"):
            return int(mem_str[:-2]) // 1024
        if mem_str.endswith("Mi"):
            return int(mem_str[:-2])
        if mem_str.endswith("Gi"):
            return int(float(mem_str[:-2]) * 1024)
        if mem_str.endswith("Ti"):
            return int(float(mem_str[:-2]) * 1024 * 1024)
        if mem_str.endswith("k"):
            return int(mem_str[:-1]) // 1024
        if mem_str.endswith("m"):
            return 0
        return int(mem_str) // (1024 * 1024)
    except Exception:
        return 0


def _fmt_mem(mem_str: str) -> str:
    """Formata memória Ki/Mi/Gi para formato legível curto ex: 16Gi, 512Mi."""
    if not mem_str or mem_str in ("N/A", "?", "<unknown>"):
        return mem_str or "?"
    try:
        mem_str = mem_str.strip()
        if mem_str.endswith("Ki"):
            ki = int(mem_str[:-2])
            if ki >= 1024 * 1024:
                return f"{ki // (1024*1024)}Gi"
            if ki >= 1024:
                return f"{ki // 1024}Mi"
            return f"{ki}Ki"
        if mem_str.endswith("Mi"):
            mi = int(mem_str[:-2])
            if mi >= 1024:
                return f"{mi // 1024}Gi"
            return f"{mi}Mi"
        if mem_str.endswith("Gi"):
            return mem_str
        return mem_str
    except Exception:
        return mem_str


def _fmt_version(version: str) -> str:
    """Abrevia versão do kubelet ex: v1.34.4+rke2r1 → v1.34.4"""
    if not version or version == "?":
        return version
    # Remove sufixo +rke2r1, +k3s1, etc
    return version.split("+")[0]


def _fmt_roles(roles_str: str) -> str:
    """Abrevia roles ex: control-plane,etcd → ctrl,etcd"""
    return roles_str.replace("control-plane", "ctrl").replace("master", "mstr")



    """Converte CPU allocatable para millicores."""
    try:
        if cpu_str.endswith("m"):
            return int(cpu_str[:-1])
        return int(float(cpu_str) * 1000)
    except Exception:
        return 1


def _parse_top_nodes(output: str) -> dict[str, dict]:
    """Parseia saída de kubectl top nodes."""
    result = {}
    for line in output.strip().splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5:
            result[parts[0]] = {
                "cpu": parts[1], "cpu_pct": parts[2].strip("%"),
                "mem": parts[3], "mem_pct": parts[4].strip("%"),
            }
    return result


def _parse_top_pods(output: str) -> dict[tuple, dict]:
    """Parseia saída de kubectl top pods --all-namespaces."""
    result = {}
    for line in output.strip().splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 4:
            result[(parts[0], parts[1])] = {
                "cpu": parts[2], "mem": parts[3],
                "cpu_m": _cpu_to_m(parts[2]),
                "mem_mib": _mem_to_mib(parts[3]),
            }
    return result


# ── Coletores individuais ─────────────────────────────────────────────────────

def collect_nodes(ctx=None) -> list[NodeInfo]:
    ok, out = _run(["get", "nodes"], ctx)
    if not ok:
        return []

    # kubectl top nodes
    top_ok, top_out = _run(["top", "nodes", "--no-headers"], ctx, output_format="")
    top_data = _parse_top_nodes(top_out) if top_ok else {}

    nodes = []
    try:
        for item in json.loads(out).get("items", []):
            meta = item["metadata"]
            labels = meta.get("labels", {})
            status = item.get("status", {})
            spec = item.get("spec", {})

            roles = [k.split("/")[-1] for k in labels if "node-role.kubernetes.io/" in k]
            roles_str = ",".join(roles) or "worker"

            ready_cond = next((c for c in status.get("conditions", []) if c["type"] == "Ready"), None)
            node_status = "Ready" if ready_cond and ready_cond["status"] == "True" else "NotReady"

            cap = status.get("capacity", {})
            alloc = status.get("allocatable", {})
            t = top_data.get(meta["name"], {})

            cpu_alloc_m = _cpu_allocatable_m(alloc.get("cpu", "0"))
            mem_alloc_mib = _mem_to_mib(alloc.get("memory", "0"))
            cpu_use_m = _cpu_to_m(t.get("cpu", "0"))
            mem_use_mib = _mem_to_mib(t.get("mem", "0"))

            nodes.append(NodeInfo(
                name=meta["name"], status=node_status,
                roles=_fmt_roles(",".join(roles) or "worker"),
                age=_age(meta["creationTimestamp"]),
                version=_fmt_version(status.get("nodeInfo", {}).get("kubeletVersion", "?")),
                cpu_capacity=cap.get("cpu", "?"),
                mem_capacity=_fmt_mem(cap.get("memory", "?")),
                cpu_allocatable=alloc.get("cpu", "?"),
                mem_allocatable=_fmt_mem(alloc.get("memory", "?")),
                cpu_usage=t.get("cpu", "N/A"), mem_usage=t.get("mem", "N/A"),
                cpu_pct=float(t.get("cpu_pct", 0) or 0),
                mem_pct=float(t.get("mem_pct", 0) or 0),
                conditions=[{"type": c["type"], "status": c["status"]}
                            for c in status.get("conditions", [])],
                taints=[f"{t.get('key')}:{t.get('effect')}"
                        for t in spec.get("taints", [])],
            ))
    except Exception as e:
        logger.error(f"Erro ao parsear nodes: {e}")
    return nodes


def collect_pods(ctx=None) -> list[PodInfo]:
    ok, out = _run(["get", "pods", "--all-namespaces"], ctx)
    if not ok:
        return []

    top_ok, top_out = _run(["top", "pods", "--all-namespaces", "--no-headers"], ctx, output_format="")
    top_data = _parse_top_pods(top_out) if top_ok else {}

    pods = []
    try:
        for item in json.loads(out).get("items", []):
            meta = item["metadata"]
            spec = item.get("spec", {})
            status = item.get("status", {})
            ns = meta.get("namespace", "?")

            containers = status.get("containerStatuses", [])
            restarts = sum(c.get("restartCount", 0) for c in containers)
            ready_ct = sum(1 for c in containers if c.get("ready", False))
            total_ct = len(containers)

            phase = status.get("phase", "Unknown")
            for c in containers:
                st = c.get("state", {})
                if "waiting" in st and st["waiting"].get("reason") == "CrashLoopBackOff":
                    phase = "CrashLoopBackOff"
                    break
                if "waiting" in st and st["waiting"].get("reason") == "OOMKilled":
                    phase = "OOMKilled"

            images = [c.get("image", "") for c in spec.get("containers", [])]
            image_str = images[0] if images else "?"
            if len(images) > 1:
                image_str += f" (+{len(images)-1})"

            t = top_data.get((ns, meta["name"]), {})
            pods.append(PodInfo(
                name=meta["name"], namespace=ns, status=phase,
                ready=f"{ready_ct}/{total_ct}", restarts=restarts,
                age=_age(meta["creationTimestamp"]),
                node=spec.get("nodeName", "?"), image=image_str,
                cpu_usage=t.get("cpu", "N/A"), mem_usage=t.get("mem", "N/A"),
                cpu_millicores=t.get("cpu_m", 0), mem_mib=t.get("mem_mib", 0),
            ))
    except Exception as e:
        logger.error(f"Erro ao parsear pods: {e}")
    return pods


def collect_deployments(ctx=None) -> list[DeploymentInfo]:
    ok, out = _run(["get", "deployments", "--all-namespaces"], ctx)
    if not ok:
        return []
    result = []
    try:
        for item in json.loads(out).get("items", []):
            meta = item["metadata"]
            spec = item.get("spec", {})
            st = item.get("status", {})
            result.append(DeploymentInfo(
                name=meta["name"], namespace=meta.get("namespace", "?"),
                desired=spec.get("replicas", 0),
                ready=st.get("readyReplicas", 0) or 0,
                available=st.get("availableReplicas", 0) or 0,
                up_to_date=st.get("updatedReplicas", 0) or 0,
                age=_age(meta["creationTimestamp"]),
            ))
    except Exception as e:
        logger.error(f"Erro ao parsear deployments: {e}")
    return result


def collect_statefulsets(ctx=None) -> list[StatefulSetInfo]:
    ok, out = _run(["get", "statefulsets", "--all-namespaces"], ctx)
    if not ok:
        return []
    result = []
    try:
        for item in json.loads(out).get("items", []):
            meta = item["metadata"]
            spec = item.get("spec", {})
            st = item.get("status", {})
            result.append(StatefulSetInfo(
                name=meta["name"], namespace=meta.get("namespace", "?"),
                desired=spec.get("replicas", 1),
                ready=st.get("readyReplicas", 0) or 0,
                age=_age(meta["creationTimestamp"]),
            ))
    except Exception as e:
        logger.error(f"Erro ao parsear statefulsets: {e}")
    return result


def collect_daemonsets(ctx=None) -> list[DaemonSetInfo]:
    ok, out = _run(["get", "daemonsets", "--all-namespaces"], ctx)
    if not ok:
        return []
    result = []
    try:
        for item in json.loads(out).get("items", []):
            meta = item["metadata"]
            st = item.get("status", {})
            result.append(DaemonSetInfo(
                name=meta["name"], namespace=meta.get("namespace", "?"),
                desired=st.get("desiredNumberScheduled", 0),
                ready=st.get("numberReady", 0),
                available=st.get("numberAvailable", 0),
                age=_age(meta["creationTimestamp"]),
            ))
    except Exception as e:
        logger.error(f"Erro ao parsear daemonsets: {e}")
    return result


def collect_cronjobs(ctx=None) -> list[CronJobInfo]:
    ok, out = _run(["get", "cronjobs", "--all-namespaces"], ctx)
    if not ok:
        return []
    result = []
    try:
        for item in json.loads(out).get("items", []):
            meta = item["metadata"]
            spec = item.get("spec", {})
            st = item.get("status", {})
            last = st.get("lastScheduleTime", "")
            result.append(CronJobInfo(
                name=meta["name"], namespace=meta.get("namespace", "?"),
                schedule=spec.get("schedule", "?"),
                last_schedule=_age(last) + " ago" if last else "nunca",
                active=len(st.get("active", [])),
                age=_age(meta["creationTimestamp"]),
            ))
    except Exception as e:
        logger.error(f"Erro ao parsear cronjobs: {e}")
    return result


def collect_jobs(ctx=None) -> list[JobInfo]:
    ok, out = _run(["get", "jobs", "--all-namespaces"], ctx)
    if not ok:
        return []
    result = []
    try:
        for item in json.loads(out).get("items", []):
            meta = item["metadata"]
            spec = item.get("spec", {})
            st = item.get("status", {})
            succeeded = st.get("succeeded", 0) or 0
            failed_ct = st.get("failed", 0) or 0
            completions = spec.get("completions", 1) or 1
            job_status = "Complete" if succeeded >= completions else ("Failed" if failed_ct > 0 else "Running")

            start = st.get("startTime", "")
            comp = st.get("completionTime", "")
            if start and comp:
                try:
                    s = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    e = datetime.fromisoformat(comp.replace("Z", "+00:00"))
                    dur = int((e - s).total_seconds())
                    duration = f"{dur//60}m{dur%60}s"
                except Exception:
                    duration = "?"
            elif start:
                duration = _age(start)
            else:
                duration = "?"

            result.append(JobInfo(
                name=meta["name"], namespace=meta.get("namespace", "?"),
                completions=f"{succeeded}/{completions}",
                duration=duration, status=job_status,
                age=_age(meta["creationTimestamp"]),
            ))
    except Exception as e:
        logger.error(f"Erro ao parsear jobs: {e}")
    return result


def collect_pvcs(ctx=None) -> list[PVCInfo]:
    ok, out = _run(["get", "pvc", "--all-namespaces"], ctx)
    if not ok:
        return []
    result = []
    try:
        for item in json.loads(out).get("items", []):
            meta = item["metadata"]
            spec = item.get("spec", {})
            st = item.get("status", {})
            vol_name = spec.get("volumeName", "?")
            # Abrevia UUID do volume para não poluir a coluna
            if vol_name and vol_name.startswith("pvc-") and len(vol_name) > 16:
                vol_name = vol_name[:15] + "…"
            result.append(PVCInfo(
                name=meta["name"], namespace=meta.get("namespace", "?"),
                status=st.get("phase", "?"),
                volume=vol_name,
                capacity=st.get("capacity", {}).get("storage", "?"),
                access_modes=",".join(spec.get("accessModes", [])),
                storage_class=spec.get("storageClassName", "?"),
                age=_age(meta["creationTimestamp"]),
            ))
    except Exception as e:
        logger.error(f"Erro ao parsear PVCs: {e}")
    return result


def collect_ingresses(ctx=None) -> list[IngressInfo]:
    ok, out = _run(["get", "ingresses", "--all-namespaces"], ctx)
    if not ok:
        return []
    result = []
    try:
        for item in json.loads(out).get("items", []):
            meta = item["metadata"]
            spec = item.get("spec", {})
            st = item.get("status", {})
            annotations = meta.get("annotations", {})

            class_name = (spec.get("ingressClassName") or
                          annotations.get("kubernetes.io/ingress.class", "?"))

            hosts = list({rule.get("host", "*") for rule in spec.get("rules", [])})
            hosts_str = ", ".join(hosts[:3])
            if len(hosts) > 3:
                hosts_str += f" (+{len(hosts)-3})"

            lb_ingress = st.get("loadBalancer", {}).get("ingress", [])
            address = ", ".join(
                i.get("ip") or i.get("hostname", "") for i in lb_ingress
            ) or "?"

            tls = spec.get("tls", [])
            ports = "443,80" if tls else "80"

            result.append(IngressInfo(
                name=meta["name"], namespace=meta.get("namespace", "?"),
                class_name=class_name, hosts=hosts_str,
                address=address, ports=ports,
                age=_age(meta["creationTimestamp"]),
            ))
    except Exception as e:
        logger.error(f"Erro ao parsear ingresses: {e}")
    return result


def collect_services(ctx=None) -> list[ServiceInfo]:
    ok, out = _run(["get", "services", "--all-namespaces"], ctx)
    if not ok:
        return []
    result = []
    try:
        for item in json.loads(out).get("items", []):
            meta = item["metadata"]
            spec = item.get("spec", {})
            st = item.get("status", {})

            svc_type = spec.get("type", "ClusterIP")
            # Só inclui LoadBalancer, NodePort e ExternalName (ClusterIP é muito verboso)
            if svc_type not in ("LoadBalancer", "NodePort", "ExternalName"):
                continue

            external = spec.get("externalIPs", [])
            lb_ingress = st.get("loadBalancer", {}).get("ingress", [])
            ext_str = ", ".join(
                i.get("ip") or i.get("hostname", "") for i in lb_ingress
            ) or (", ".join(external) if external else "?")

            ports = spec.get("ports", [])
            ports_str = ", ".join(
                f"{p.get('port')}" + (f":{p.get('nodePort')}" if p.get("nodePort") else "")
                for p in ports[:4]
            )

            result.append(ServiceInfo(
                name=meta["name"], namespace=meta.get("namespace", "?"),
                type=svc_type, cluster_ip=spec.get("clusterIP", "?"),
                external_ip=ext_str, ports=ports_str,
                age=_age(meta["creationTimestamp"]),
            ))
    except Exception as e:
        logger.error(f"Erro ao parsear services: {e}")
    return result


def collect_hpas(ctx=None) -> list[HPAInfo]:
    ok, out = _run(["get", "hpa", "--all-namespaces"], ctx)
    if not ok:
        return []
    result = []
    try:
        for item in json.loads(out).get("items", []):
            meta = item["metadata"]
            spec = item.get("spec", {})
            st = item.get("status", {})

            target_ref = spec.get("scaleTargetRef", {})
            target = f"{target_ref.get('kind','?')}/{target_ref.get('name','?')}"

            metrics = spec.get("metrics", [])
            cpu_target = "?"
            for m in metrics:
                if m.get("type") == "Resource" and m.get("resource", {}).get("name") == "cpu":
                    util = m["resource"].get("target", {}).get("averageUtilization")
                    if util:
                        cpu_target = f"{util}%"

            current_metrics = st.get("currentMetrics", [])
            cpu_current = "?"
            for m in current_metrics:
                if m.get("type") == "Resource" and m.get("resource", {}).get("name") == "cpu":
                    util = m["resource"].get("current", {}).get("averageUtilization")
                    if util is not None:
                        cpu_current = f"{util}%"

            result.append(HPAInfo(
                name=meta["name"], namespace=meta.get("namespace", "?"),
                target=target,
                min_replicas=spec.get("minReplicas", 1),
                max_replicas=spec.get("maxReplicas", 1),
                current_replicas=st.get("currentReplicas", 0),
                cpu_target_pct=cpu_target,
                cpu_current_pct=cpu_current,
                age=_age(meta["creationTimestamp"]),
            ))
    except Exception as e:
        logger.error(f"Erro ao parsear HPAs: {e}")
    return result


def collect_events(ctx=None, limit: int = 60, exclude_namespaces: list = None) -> list[EventInfo]:
    ok, out = _run(["get", "events", "--all-namespaces",
                    "--field-selector", "type=Warning",
                    "--sort-by=.lastTimestamp"], ctx)
    if not ok:
        return []

    # Namespaces a excluir dos eventos (ex: o próprio namespace do status-report)
    exclude = set(exclude_namespaces or ["status-report"])

    result = []
    try:
        items = json.loads(out).get("items", [])
        for item in items[-limit:]:
            meta = item["metadata"]
            ns = meta.get("namespace", "?")
            if ns in exclude:
                continue
            result.append(EventInfo(
                namespace=ns,
                type=item.get("type", "?"),
                reason=item.get("reason", "?"),
                object=f"{item.get('involvedObject',{}).get('kind','?')}/{item.get('involvedObject',{}).get('name','?')}",
                message=item.get("message", "")[:120],
                count=item.get("count", 1),
                last_seen=_age(item.get("lastTimestamp") or meta.get("creationTimestamp", "")),
            ))
    except Exception as e:
        logger.error(f"Erro ao parsear events: {e}")
    return list(reversed(result))  # mais recentes primeiro


def collect_namespaces(pods: list[PodInfo], ctx=None) -> list[NamespaceInfo]:
    ok, out = _run(["get", "namespaces"], ctx)
    if not ok:
        return []

    ns_pods: dict[str, list] = {}
    for p in pods:
        ns_pods.setdefault(p.namespace, []).append(p)

    result = []
    try:
        for item in json.loads(out).get("items", []):
            meta = item["metadata"]
            ns = meta["name"]
            plist = ns_pods.get(ns, [])
            cpu_total = sum(p.cpu_millicores for p in plist)
            mem_total = sum(p.mem_mib for p in plist)
            result.append(NamespaceInfo(
                name=ns, status=item.get("status", {}).get("phase", "?"),
                age=_age(meta["creationTimestamp"]),
                pod_count=len(plist),
                running=sum(1 for p in plist if p.status == "Running"),
                pending=sum(1 for p in plist if p.status == "Pending"),
                failed=sum(1 for p in plist if p.status in ("Failed", "CrashLoopBackOff", "OOMKilled")),
                cpu_usage_m=cpu_total, mem_usage_mib=mem_total,
            ))
    except Exception as e:
        logger.error(f"Erro ao parsear namespaces: {e}")
    return result


def build_summary(report: ClusterReport) -> dict:
    pods = report.pods
    total = len(pods)
    running = sum(1 for p in pods if p.status == "Running")
    pending = sum(1 for p in pods if p.status == "Pending")
    failed  = sum(1 for p in pods if p.status in ("Failed", "CrashLoopBackOff", "OOMKilled"))
    crash   = sum(1 for p in pods if p.status == "CrashLoopBackOff")
    oom     = sum(1 for p in pods if p.status == "OOMKilled")
    # Pods com restarts elevados — threshold maior para componentes de sistema
    SYSTEM_NS = {"kube-system", "kube-node-lease", "kube-public",
                 "cattle-system", "cattle-fleet-system", "cattle-fleet-local-system",
                 "cattle-capi-system", "cattle-turtles-system", "fleet-default",
                 "fleet-local", "local", "local-path-storage"}
    high_r = [p for p in pods if (
        (p.namespace in SYSTEM_NS and p.restarts >= 20) or
        (p.namespace not in SYSTEM_NS and p.restarts >= 5)
    )]

    nodes_ready = sum(1 for n in report.nodes if n.status == "Ready")
    pvcs_bound  = sum(1 for p in report.pvcs if p.status == "Bound")
    pvcs_lost   = sum(1 for p in report.pvcs if p.status == "Lost")

    # Workloads
    deploys = report.deployments
    sts_list = report.statefulsets
    ds_list  = report.daemonsets
    deploys_degraded = sum(1 for d in deploys if d.ready < d.desired)
    sts_degraded     = sum(1 for s in sts_list if s.ready < s.desired)
    ds_degraded      = sum(1 for d in ds_list if d.ready < d.desired)

    # Eventos críticos
    warning_events = len([e for e in report.events if e.type == "Warning"])

    # Top pods CPU/Mem (com métricas)
    pods_with_metrics = [p for p in pods if p.cpu_millicores > 0 or p.mem_mib > 0]
    top_cpu = sorted(pods_with_metrics, key=lambda p: p.cpu_millicores, reverse=True)[:10]
    top_mem = sorted(pods_with_metrics, key=lambda p: p.mem_mib, reverse=True)[:10]

    # Score de saúde (ponderado)
    score = 100.0
    if total > 0:
        score -= (failed / total) * 40
        score -= (pending / total) * 10
    score -= (len(report.nodes) - nodes_ready) * 15
    score -= deploys_degraded * 3
    score -= sts_degraded * 3
    score -= pvcs_lost * 5
    score -= min(warning_events * 0.5, 10)
    score = max(0.0, min(100.0, round(score, 1)))

    return {
        # Nodes
        "total_nodes": len(report.nodes), "nodes_ready": nodes_ready,
        "nodes_not_ready": len(report.nodes) - nodes_ready,
        # Namespaces
        "total_namespaces": len(report.namespaces),
        # Pods
        "total_pods": total, "pods_running": running, "pods_pending": pending,
        "pods_failed": failed, "pods_crashloop": crash, "pods_oom": oom,
        "pods_high_restarts": len(high_r),
        "high_restart_pods": [{"name": p.name, "ns": p.namespace, "restarts": p.restarts} for p in high_r[:15]],
        # Workloads
        "total_deployments": len(deploys),
        "deployments_ok": sum(1 for d in deploys if d.ready == d.desired and d.desired > 0),
        "deployments_degraded": deploys_degraded,
        "total_statefulsets": len(sts_list), "sts_degraded": sts_degraded,
        "total_daemonsets": len(ds_list), "ds_degraded": ds_degraded,
        "total_cronjobs": len(report.cronjobs),
        "total_jobs": len(report.jobs),
        "jobs_failed": sum(1 for j in report.jobs if j.status == "Failed"),
        # Storage / Network
        "total_pvcs": len(report.pvcs), "pvcs_bound": pvcs_bound, "pvcs_lost": pvcs_lost,
        "total_ingresses": len(report.ingresses),
        "total_services_exposed": len(report.services),
        "total_hpas": len(report.hpas),
        # Events
        "warning_events": warning_events,
        # Top recursos
        "top_cpu_pods": [{"name": p.name, "ns": p.namespace, "cpu": p.cpu_usage, "cpu_m": p.cpu_millicores} for p in top_cpu],
        "top_mem_pods": [{"name": p.name, "ns": p.namespace, "mem": p.mem_usage, "mem_mib": p.mem_mib} for p in top_mem],
        # Score
        "health_score": score,
    }


def collect_all(cluster_name: str = "default", context: Optional[str] = None) -> ClusterReport:
    logger.info(f"[{cluster_name}] Iniciando coleta completa...")
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    report = ClusterReport(collected_at=ts, cluster_name=cluster_name, context=context)

    steps = [
        ("nodes",        lambda: collect_nodes(context)),
        ("pods",         lambda: collect_pods(context)),
        ("deployments",  lambda: collect_deployments(context)),
        ("statefulsets", lambda: collect_statefulsets(context)),
        ("daemonsets",   lambda: collect_daemonsets(context)),
        ("cronjobs",     lambda: collect_cronjobs(context)),
        ("jobs",         lambda: collect_jobs(context)),
        ("pvcs",         lambda: collect_pvcs(context)),
        ("ingresses",    lambda: collect_ingresses(context)),
        ("services",     lambda: collect_services(context)),
        ("hpas",         lambda: collect_hpas(context)),
        ("events",       lambda: collect_events(context, exclude_namespaces=["status-report"])),
    ]

    for attr, fn in steps:
        try:
            setattr(report, attr, fn())
            logger.info(f"  ✓ {attr}: {len(getattr(report, attr))} items")
        except Exception as e:
            logger.warning(f"  ✗ {attr}: {e}")
            report.errors.append(f"Erro ao coletar {attr}: {e}")

    # Namespaces (depende de pods para contagem)
    try:
        report.namespaces = collect_namespaces(report.pods, context)
        logger.info(f"  ✓ namespaces: {len(report.namespaces)} items")
    except Exception as e:
        report.errors.append(f"Erro ao coletar namespaces: {e}")

    report.summary = build_summary(report)
    logger.info(f"[{cluster_name}] Coleta concluída — Health: {report.summary['health_score']}%")
    return report
