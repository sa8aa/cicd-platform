from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Deployment, Notification
from integrations.jenkins_client import JenkinsClient


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
