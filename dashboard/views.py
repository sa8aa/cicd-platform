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
