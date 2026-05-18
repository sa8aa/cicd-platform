import json
import time
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import StreamingHttpResponse
from .models import Deployment, Notification, DeploymentLog, DeploymentStage
from integrations.jenkins_client import JenkinsClient


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _detect_level(line: str) -> tuple:
    """Detect log level from a Jenkins log line."""
    line_lower = line.lower()
    if 'error' in line_lower or 'failed' in line_lower or 'exception' in line_lower:
        return 'ERROR', 'log-ERROR'
    elif 'warning' in line_lower or 'warn' in line_lower:
        return 'WARNING', 'log-WARNING'
    elif any(x in line for x in ['✅', 'successfully', 'SUCCESS', 'pushed', 'deployed']):
        return 'SUCCESS', 'log-SUCCESS'
    return 'INFO', 'log-INFO'


def _stream_generator(deployment_pk: int):
    """
    Generator that polls Jenkins progressiveText every 1.5s
    and yields SSE events with new log lines and stage updates.
    """
    client    = JenkinsClient()
    start     = 0
    max_loops = 400  # ~10 minutes max

    for _ in range(max_loops):
        try:
            dep = Deployment.objects.get(pk=deployment_pk)
        except Deployment.DoesNotExist:
            break

        # If finished — send final event and stop
        if dep.status in ('SUCCESS', 'FAILED', 'CANCELLED'):
            yield _sse_event('done', {
                'status':   dep.status,
                'duration': str(dep.duration) if dep.duration else '',
            })
            break

        if dep.jenkins_build_number:
            # ── Get new log lines ──────────────────────────────────────────
            result      = client.get_progressive_console(
                dep.project.jenkins_job_name,
                dep.jenkins_build_number,
                start)
            text        = result.get('text', '')
            start       = result.get('next_offset', start)
            more        = result.get('more', False)

            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                level, css = _detect_level(line)
                DeploymentLog.objects.get_or_create(
                    deployment=dep,
                    message=f'[Jenkins] {line}',
                    defaults={'level': level})
                yield _sse_event('log', {
                    'level':     level,
                    'message':   f'[Jenkins] {line}',
                    'css_class': css,
                })

            # ── Get stage statuses ─────────────────────────────────────────
            stages = client.get_build_stages(
                dep.project.jenkins_job_name,
                dep.jenkins_build_number)
            if stages:
                for js in stages:
                    DeploymentStage.objects.filter(
                        deployment=dep,
                        name__icontains=js['name'].split()[0]
                    ).update(status=js['status'])
                yield _sse_event('stages', {'stages': stages})

            # ── Check if build finished ────────────────────────────────────
            if not more:
                build_info = client.get_build_info(
                    dep.project.jenkins_job_name,
                    dep.jenkins_build_number)
                result_str = build_info.get('result')
                if result_str in ('SUCCESS', 'FAILURE', 'ABORTED'):
                    final = {'SUCCESS': 'SUCCESS',
                             'FAILURE': 'FAILED',
                             'ABORTED': 'CANCELLED'}.get(result_str, 'FAILED')
                    dep.mark_finished(final)
                    yield _sse_event('done', {
                        'status':   final,
                        'duration': str(dep.duration) if dep.duration else '',
                    })
                    break

        # Keepalive ping every loop
        yield _sse_event('ping', {'t': int(time.time())})
        time.sleep(1.5)

    yield _sse_event('done', {'status': 'TIMEOUT', 'duration': ''})


# ── Views ─────────────────────────────────────────────────────────────────────

@login_required
def deployment_stream(request, pk):
    """SSE endpoint — streams Jenkins logs in real time."""
    dep = get_object_or_404(Deployment, pk=pk)
    response = StreamingHttpResponse(
        _stream_generator(dep.pk),
        content_type='text/event-stream')
    response['Cache-Control']     = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@login_required
def deployment_detail(request, pk):
    dep    = get_object_or_404(Deployment, pk=pk)
    stages = dep.stages.all()
    logs   = dep.logs.order_by('timestamp')
    return render(request, 'deployments/detail.html', {
        'deployment': dep,
        'stages':     stages,
        'logs':       logs,
    })


@login_required
def deployment_cancel(request, pk):
    dep = get_object_or_404(Deployment, pk=pk)
    if request.method == 'POST':
        if dep.status in ('PENDING', 'RUNNING'):
            if dep.jenkins_build_number:
                client = JenkinsClient()
                client.abort_build(dep.project.jenkins_job_name,
                                   dep.jenkins_build_number)
            dep.mark_finished('CANCELLED', 'Annulé manuellement.')
            messages.success(request, 'Déploiement annulé.')
        else:
            messages.warning(request, 'Ce déploiement ne peut pas être annulé.')
    return redirect('deployment_detail', pk=pk)


@login_required
def notifications_view(request):
    notifs = Notification.objects.filter(user=request.user)
    notifs.filter(is_read=False).update(is_read=True)
    return render(request, 'deployments/notifications.html',
                  {'notifications': notifs})
