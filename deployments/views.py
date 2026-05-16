import json
import time
import logging

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import StreamingHttpResponse, HttpResponse
from django.utils import timezone

from .models import Deployment, DeploymentLog, Notification
from integrations.jenkins_client import JenkinsClient

logger = logging.getLogger(__name__)


@login_required
def deployment_detail(request, pk):
    dep    = get_object_or_404(Deployment, pk=pk)
    stages = dep.stages.all()
    logs   = dep.logs.order_by('timestamp')
    return render(request, 'deployments/detail.html', {
        'deployment': dep, 'stages': stages, 'logs': logs,
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


# ── SSE helpers ────────────────────────────────────────────────────────────

def _sse_event(event_type, data):
    """Format a single SSE message."""
    payload = json.dumps(data, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


def _level_css(level):
    return {
        'INFO':    'log-INFO',
        'SUCCESS': 'log-SUCCESS',
        'WARNING': 'log-WARNING',
        'ERROR':   'log-ERROR',
    }.get(level, 'log-INFO')


def _stream_generator(deployment_pk, user):
    """
    Generator that yields SSE events for a deployment.

    Events emitted:
      - "log"    : { level, message, timestamp, css_class }
      - "stage"  : { stages: [{name, status, duration}] }
      - "status" : { status }   — emitted when the deployment finishes
      - "done"   : {}           — signals the client to close the connection
    """
    try:
        dep = Deployment.objects.get(pk=deployment_pk)
    except Deployment.DoesNotExist:
        yield _sse_event('done', {'reason': 'not_found'})
        return

    # Send all existing DB logs first (so the console isn't blank on connect)
    last_log_id = 0
    existing_logs = DeploymentLog.objects.filter(
        deployment=dep).order_by('timestamp', 'id')
    for log in existing_logs:
        yield _sse_event('log', {
            'level':     log.level,
            'message':   log.message,
            'timestamp': log.timestamp.strftime('%H:%M:%S'),
            'css_class': _level_css(log.level),
        })
        last_log_id = log.id

    # Send current stage snapshot
    yield _sse_event('stage', {
        'stages': list(dep.stages.values('name', 'status', 'order'))
    })

    # If already finished, we're done
    if dep.status not in ('PENDING', 'RUNNING'):
        yield _sse_event('status', {'status': dep.status})
        yield _sse_event('done', {})
        return

    # --- Live polling loop ---
    jenkins_byte_offset = 0   # progressive console byte position
    client = JenkinsClient()
    poll_interval = 1.5  # seconds between polls
    max_wait = 60 * 30   # 30 min hard limit
    elapsed = 0

    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval

        # Refresh deployment from DB
        try:
            dep.refresh_from_db()
        except Exception:
            break

        # --- 1. Stream any new DB log entries (created by the webhook) ---
        new_logs = DeploymentLog.objects.filter(
            deployment=dep, id__gt=last_log_id
        ).order_by('timestamp', 'id')
        for log in new_logs:
            yield _sse_event('log', {
                'level':     log.level,
                'message':   log.message,
                'timestamp': log.timestamp.strftime('%H:%M:%S'),
                'css_class': _level_css(log.level),
            })
            last_log_id = log.id

        # --- 2. Fetch live Jenkins console progressively ---
        if dep.jenkins_build_number and client.is_connected():
            try:
                new_text, jenkins_byte_offset = client.get_build_console(
                    dep.project.jenkins_job_name,
                    dep.jenkins_build_number,
                    start_byte=jenkins_byte_offset,
                )
                if new_text:
                    for line in new_text.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        level = 'INFO'
                        if any(kw in line for kw in ['ERROR', 'FAILED', 'error', 'failed', 'Exception']):
                            level = 'ERROR'
                        elif any(kw in line for kw in ['WARNING', 'WARN', 'warning']):
                            level = 'WARNING'
                        elif any(kw in line for kw in ['SUCCESS', 'successfully', 'Finished: SUCCESS']):
                            level = 'SUCCESS'
                        yield _sse_event('log', {
                            'level':     level,
                            'message':   f'[Jenkins] {line}',
                            'timestamp': timezone.now().strftime('%H:%M:%S'),
                            'css_class': _level_css(level),
                            'source':    'jenkins',
                        })
            except Exception as e:
                logger.debug(f"Jenkins console fetch error: {e}")

        # --- 3. Stream updated stage statuses ---
        yield _sse_event('stage', {
            'stages': list(dep.stages.values('name', 'status', 'order'))
        })

        # --- 4. Check if deployment finished ---
        if dep.status not in ('PENDING', 'RUNNING'):
            yield _sse_event('status', {'status': dep.status})
            # Send a heartbeat pause then close
            time.sleep(1)
            yield _sse_event('done', {})
            return

        # Keep-alive heartbeat (prevents proxy timeouts)
        yield f": heartbeat {int(elapsed)}s\n\n"

    # Timeout reached
    yield _sse_event('done', {'reason': 'timeout'})


@login_required
def stream_logs(request, pk):
    """
    SSE endpoint — streams deployment logs and stage updates in real time.
    Usage: GET /deployments/<pk>/stream/
    """
    dep = get_object_or_404(Deployment, pk=pk)

    response = StreamingHttpResponse(
        _stream_generator(dep.pk, request.user),
        content_type='text/event-stream',
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'   # disables Nginx buffering
    return response
