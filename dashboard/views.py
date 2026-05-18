from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate, logout
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta

from projects.models import Project
from deployments.models import Deployment, Notification


@login_required
def home(request):
    user = request.user
    now  = timezone.now()
    last_7d = now - timedelta(days=7)

    projects = Project.objects.filter(owner=user) \
        if user.role != 'admin' else Project.objects.all()

    recent_deps = Deployment.objects.filter(
        project__in=projects,
        started_at__gte=last_7d,
    ).select_related('project', 'triggered_by').order_by('-started_at')[:8]

    total   = Deployment.objects.filter(project__in=projects,
                                         started_at__gte=last_7d).count()
    success = Deployment.objects.filter(project__in=projects,
                started_at__gte=last_7d, status='SUCCESS').count()
    failed  = Deployment.objects.filter(project__in=projects,
                started_at__gte=last_7d, status='FAILED').count()
    running = Deployment.objects.filter(project__in=projects,
                status='RUNNING').count()

    # Chart data: last 7 days
    labels, s_data, f_data = [], [], []
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        labels.append(day.strftime('%d/%m'))
        s_data.append(Deployment.objects.filter(
            project__in=projects, started_at__date=day.date(),
            status='SUCCESS').count())
        f_data.append(Deployment.objects.filter(
            project__in=projects, started_at__date=day.date(),
            status='FAILED').count())

    notifs = Notification.objects.filter(user=user, is_read=False)[:5]

    return render(request, 'dashboard/home.html', {
        'projects': projects[:6],
        'recent_deps': recent_deps,
        'total': total,
        'success': success,
        'failed': failed,
        'running': running,
        'success_rate': round((success/total*100), 1) if total else 0,
        'labels': labels,
        's_data': s_data,
        'f_data': f_data,
        'notifs': notifs,
    })


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        user = authenticate(request,
            username=request.POST.get('username'),
            password=request.POST.get('password'))
        if user:
            login(request, user)
            return redirect('dashboard')
        messages.error(request, 'Identifiants invalides.')
    return render(request, 'registration/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def monitoring(request):
    from django.conf import settings
    from deployments.models import Deployment
    from projects.models import Project
    import urllib.request

    # Stats
    total = Deployment.objects.count()
    success = Deployment.objects.filter(status='SUCCESS').count()
    failed  = Deployment.objects.filter(status='FAILED').count()
    running = Deployment.objects.filter(status='RUNNING').count()
    success_rate = round((success / total * 100), 1) if total else 0

    recent_deployments = Deployment.objects.select_related(
        'project').order_by('-started_at')[:8]

    # Fetch raw metrics from Django /metrics/
    metrics = []
    try:
        req = urllib.request.urlopen(
            'http://localhost:8000/metrics/', timeout=2)
        raw = req.read().decode('utf-8')
        metrics = [line for line in raw.split('\n')
                   if line.strip() and 'cicd_' in line or line.startswith('#')][:30]
    except Exception:
        metrics = ['# Métriques non disponibles']

    # Grafana URLs
    grafana_url = getattr(settings, 'GRAFANA_URL', 'http://localhost:3000')
    grafana_dashboard_url = (
        f"{grafana_url}/d/cicd-platform/ci-cd-platform-deployments"
        f"?orgId=1&refresh=5s&kiosk=tv")
    prometheus_url = 'http://localhost:9090'

    return render(request, 'dashboard/monitoring.html', {
        'total_deployments': total,
        'success_rate': success_rate,
        'failed': failed,
        'running': running,
        'recent_deployments': recent_deployments,
        'metrics': metrics,
        'grafana_url': grafana_url,
        'grafana_dashboard_url': grafana_dashboard_url,
        'prometheus_url': prometheus_url,
    })
