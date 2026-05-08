from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse

from .models import Project
from .forms import ProjectForm
from deployments.models import Deployment, DeploymentStage
from integrations.jenkins_client import JenkinsClient
from integrations.jenkinsfile_generator import generate_jenkinsfile


@login_required
def project_list(request):
    projects = Project.objects.filter(owner=request.user) \
        if request.user.role != 'admin' else Project.objects.all()
    return render(request, 'projects/list.html', {'projects': projects})


STAGE_LIST = [
    'Checkout', 'Install Dependencies', 'Run Tests',
    'Build & Push Images', 'Provision Infra', 'Deploy to k3s',
]


@login_required
def project_create(request):
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.owner = request.user
            project.save()

            # Generate Jenkinsfile and create Jenkins job
            jenkinsfile = generate_jenkinsfile(project)
            client = JenkinsClient()
            created = client.create_or_update_job(
                project.jenkins_job_name,
                jenkinsfile,
                description=project.description,
            )
            if created:
                project.jenkins_created = True
                project.save(update_fields=['jenkins_created'])
                messages.success(request,
                    f'Projet «{project.name}» créé et job Jenkins configuré ✅')
            else:
                messages.warning(request,
                    f'Projet créé mais Jenkins indisponible. '
                    f'Le Jenkinsfile est disponible dans les détails.')

            return redirect('project_detail', pk=project.pk)
    else:
        form = ProjectForm()
    return render(request, 'projects/form.html', {
        'form': form, 'action': 'Créer', 'title': 'Nouveau projet',
        'stage_list': STAGE_LIST})


@login_required
def project_edit(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            project = form.save()
            # Regenerate Jenkinsfile
            jenkinsfile = generate_jenkinsfile(project)
            client = JenkinsClient()
            client.create_or_update_job(
                project.jenkins_job_name, jenkinsfile, project.description)
            messages.success(request, f'Projet «{project.name}» mis à jour ✅')
            return redirect('project_detail', pk=project.pk)
    else:
        form = ProjectForm(instance=project)
    return render(request, 'projects/form.html', {
        'form': form, 'action': 'Modifier', 'title': f'Modifier {project.name}',
        'project': project, 'stage_list': STAGE_LIST})


@login_required
def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk)
    deployments = project.deployments.order_by('-started_at')[:15]
    jenkinsfile  = generate_jenkinsfile(project)
    return render(request, 'projects/detail.html', {
        'project': project,
        'deployments': deployments,
        'jenkinsfile': jenkinsfile,
    })


@login_required
def project_delete(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        client = JenkinsClient()
        client.delete_job(project.jenkins_job_name)
        project.delete()
        messages.success(request, 'Projet supprimé.')
        return redirect('project_list')
    return render(request, 'projects/confirm_delete.html', {'project': project})


@login_required
def project_deploy(request, pk):
    """Manually trigger a build from the dashboard."""
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        client = JenkinsClient()
        # Create Deployment record
        deployment = Deployment.objects.create(
            project=project,
            status='PENDING',
            triggered_by=request.user,
        )
        # Create the 6 stage records (all PENDING)
        stage_names = [
            'Checkout', 'Install Dependencies', 'Run Tests',
            'Build & Push Images', 'Provision Infra', 'Deploy to k3s',
        ]
        for i, name in enumerate(stage_names):
            DeploymentStage.objects.create(
                deployment=deployment, name=name, order=i)

        try:
            result = client.trigger_build(project.jenkins_job_name)
            if result.get('mock'):
                deployment.status = 'RUNNING'
                deployment.save(update_fields=['status'])
                messages.info(request,
                    'Jenkins non connecté — déploiement simulé.')
            else:
                deployment.status = 'RUNNING'
                deployment.save(update_fields=['status'])
                messages.success(request,
                    f'Pipeline déclenché! Suivez le déploiement #'
                    f'{deployment.pk}')
        except Exception as e:
            deployment.mark_finished('FAILED', str(e))
            messages.error(request, f'Erreur Jenkins: {e}')

        return redirect('deployment_detail', pk=deployment.pk)
    return redirect('project_detail', pk=pk)


@login_required
def jenkinsfile_download(request, pk):
    """Download the generated Jenkinsfile."""
    project = get_object_or_404(Project, pk=pk)
    content = generate_jenkinsfile(project)
    response = HttpResponse(content, content_type='text/plain')
    response['Content-Disposition'] = f'attachment; filename="Jenkinsfile"'
    return response
