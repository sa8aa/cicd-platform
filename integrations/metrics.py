"""
Prometheus metrics for the CI/CD Platform.
Pushes metrics to Pushgateway after each deployment event.
Also exposes a /metrics/ endpoint for direct scraping.
"""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

# ── Metric definitions ────────────────────────────────────────────────────────
try:
    from prometheus_client import (
        CollectorRegistry, Counter, Gauge, Histogram,
        push_to_gateway, REGISTRY, generate_latest, CONTENT_TYPE_LATEST
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client not installed. pip install prometheus-client")


def push_deployment_metrics(deployment):
    """
    Push metrics to Prometheus Pushgateway after a deployment finishes.
    Called from deployments/models.py → mark_finished()
    """
    if not PROMETHEUS_AVAILABLE:
        return False
    try:
        registry = CollectorRegistry()

        project_name = deployment.project.name
        status       = deployment.status
        build_number = str(deployment.jenkins_build_number or 0)
        environment  = deployment.project.environment

        labels = {
            'project':      project_name,
            'status':       status,
            'build_number': build_number,
            'environment':  environment,
        }

        # ── Counter: total deployments ────────────────────────────────────
        from prometheus_client import Counter as PCounter
        dep_counter = PCounter(
            'cicd_deployments_total',
            'Total number of deployments',
            list(labels.keys()),
            registry=registry)
        dep_counter.labels(**labels).inc()

        # ── Gauge: deployment duration in seconds ─────────────────────────
        if deployment.duration:
            duration_seconds = deployment.duration.total_seconds()
            dur_gauge = Gauge(
                'cicd_deployment_duration_seconds',
                'Deployment duration in seconds',
                list(labels.keys()),
                registry=registry)
            dur_gauge.labels(**labels).set(duration_seconds)

        # ── Gauge: currently running deployments ──────────────────────────
        from deployments.models import Deployment
        running_count = Deployment.objects.filter(status='RUNNING').count()
        running_gauge = Gauge(
            'cicd_deployments_running',
            'Number of currently running deployments',
            registry=registry)
        running_gauge.set(running_count)

        # ── Push to Pushgateway ───────────────────────────────────────────
        pushgateway_url = getattr(settings, 'PROMETHEUS_PUSHGATEWAY_URL',
                                  'http://localhost:9091')
        push_to_gateway(
            pushgateway_url,
            job='cicd_platform',
            registry=registry)

        logger.info(f"Metrics pushed for deployment #{deployment.id} "
                    f"({project_name} → {status})")
        return True

    except Exception as e:
        logger.error(f"Failed to push metrics: {e}")
        return False


def push_stage_metrics(deployment):
    """
    Push per-stage duration metrics after deployment finishes.
    """
    if not PROMETHEUS_AVAILABLE:
        return False
    try:
        registry = CollectorRegistry()
        stage_gauge = Gauge(
            'cicd_stage_duration_seconds',
            'Duration of each pipeline stage in seconds',
            ['project', 'stage', 'status'],
            registry=registry)

        for stage in deployment.stages.all():
            if stage.duration:
                stage_gauge.labels(
                    project=deployment.project.name,
                    stage=stage.name,
                    status=stage.status,
                ).set(stage.duration.total_seconds())

        pushgateway_url = getattr(settings, 'PROMETHEUS_PUSHGATEWAY_URL',
                                  'http://localhost:9091')
        push_to_gateway(pushgateway_url, job='cicd_stages', registry=registry)
        return True

    except Exception as e:
        logger.error(f"Failed to push stage metrics: {e}")
        return False


def push_log_metric(deployment, level, message):
    """
    Push a single log entry as a metric label (for Grafana Logs panel).
    """
    if not PROMETHEUS_AVAILABLE:
        return False
    try:
        registry = CollectorRegistry()
        log_counter = __import__('prometheus_client').Counter(
            'cicd_log_entries_total',
            'Total log entries by level',
            ['project', 'level'],
            registry=registry)
        log_counter.labels(
            project=deployment.project.name,
            level=level,
        ).inc()

        pushgateway_url = getattr(settings, 'PROMETHEUS_PUSHGATEWAY_URL',
                                  'http://localhost:9091')
        push_to_gateway(pushgateway_url, job='cicd_logs', registry=registry)
        return True
    except Exception as e:
        logger.error(f"Failed to push log metric: {e}")
        return False
