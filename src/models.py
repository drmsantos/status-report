#!/usr/bin/env python3
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versão:  2.0.0
# Arquivo: models.py
# Desc:    Modelos de dados do K8s Status Report v2
# =============================================================================

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NodeInfo:
    name: str
    status: str
    roles: str
    age: str
    version: str
    cpu_capacity: str
    mem_capacity: str
    cpu_allocatable: str
    mem_allocatable: str
    cpu_usage: str = "N/A"       # kubectl top
    mem_usage: str = "N/A"
    cpu_pct: float = 0.0
    mem_pct: float = 0.0
    conditions: list = field(default_factory=list)
    taints: list = field(default_factory=list)


@dataclass
class PodInfo:
    name: str
    namespace: str
    status: str
    ready: str
    restarts: int
    age: str
    node: str
    image: str
    cpu_usage: str = "N/A"
    mem_usage: str = "N/A"
    cpu_millicores: int = 0
    mem_mib: int = 0
    last_restart_ago: str = 'N/A'


@dataclass
class DeploymentInfo:
    name: str
    namespace: str
    desired: int
    ready: int
    available: int
    up_to_date: int
    age: str


@dataclass
class StatefulSetInfo:
    name: str
    namespace: str
    desired: int
    ready: int
    age: str


@dataclass
class DaemonSetInfo:
    name: str
    namespace: str
    desired: int
    ready: int
    available: int
    age: str


@dataclass
class CronJobInfo:
    name: str
    namespace: str
    schedule: str
    last_schedule: str
    active: int
    age: str


@dataclass
class JobInfo:
    name: str
    namespace: str
    completions: str
    duration: str
    status: str
    age: str


@dataclass
class PVCInfo:
    name: str
    namespace: str
    status: str
    volume: str
    capacity: str
    access_modes: str
    storage_class: str
    age: str
    age_days: float = 0.0


@dataclass
class IngressInfo:
    name: str
    namespace: str
    class_name: str
    hosts: str
    address: str
    ports: str
    age: str


@dataclass
class ServiceInfo:
    name: str
    namespace: str
    type: str
    cluster_ip: str
    external_ip: str
    ports: str
    age: str


@dataclass
class HPAInfo:
    name: str
    namespace: str
    target: str
    min_replicas: int
    max_replicas: int
    current_replicas: int
    cpu_target_pct: str
    cpu_current_pct: str
    age: str


@dataclass
class EventInfo:
    namespace: str
    type: str        # Warning / Normal
    reason: str
    object: str
    message: str
    count: int
    last_seen: str


@dataclass
class NamespaceInfo:
    name: str
    status: str
    age: str
    pod_count: int
    running: int
    pending: int
    failed: int
    cpu_usage_m: int = 0    # millicores
    mem_usage_mib: int = 0


@dataclass
class HistoricalSnapshot:
    """Um snapshot anterior carregado do cache JSON."""
    collected_at: str
    cluster_name: str
    summary: dict = field(default_factory=dict)


@dataclass
class ClusterReport:
    collected_at: str
    cluster_name: str
    context: Optional[str] = None

    nodes: list = field(default_factory=list)
    namespaces: list = field(default_factory=list)
    pods: list = field(default_factory=list)
    deployments: list = field(default_factory=list)
    statefulsets: list = field(default_factory=list)
    daemonsets: list = field(default_factory=list)
    cronjobs: list = field(default_factory=list)
    jobs: list = field(default_factory=list)
    pvcs: list = field(default_factory=list)
    ingresses: list = field(default_factory=list)
    services: list = field(default_factory=list)
    hpas: list = field(default_factory=list)
    events: list = field(default_factory=list)

    summary: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    # Histórico para comparativo
    previous: Optional[HistoricalSnapshot] = None
