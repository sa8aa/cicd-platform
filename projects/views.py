import time
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse

from .models import Project
from .forms import ProjectForm
from deployments.models import Deployment, DeploymentStage
from integrations.jenkins_client import JenkinsClient
from integrations.jenkinsfile_generator import generate_jenkinsfile
from integrations.jenkins_credentials import JenkinsCredentialsManager

STAGE_LIST = [
    'Checkout', 'Install Dependencies', 'Run Tests',
    'Build & Push Images', 'Provision Infra', 'Deploy to k3s',
]

CRED_LIST = [
    'DockerHub Token',
    'AWS Access Key + Secret',
    'AWS Session Token',
    'EC2 SSH Key (.pem)',
]


def _setup_jenkins(project, request):
    client   = JenkinsClient()
    cred_mgr = JenkinsCredentialsManager()

    cred_results = cred_mgr.push_all_credentials(project)
    creds_ok = all(cred_results.values()) if cred_results else False

    if creds_ok:
        project.jenkins_creds_created = True
        project.save(update_fields=['jenkins_creds_created'])

    jenkinsfile = generate_jenkinsfile(project)
    job_created = client.create_or_update_job(
        project.jenkins_job_name, jenkinsfile, project.description)

    if job_created:
        project.jenkins_created = True
        project.save(update_fields=['jenkins_created'])
        messages.success(request,
            f'✅ Projet «{project.name}» configuré — '
            f'Job Jenkins créé + credentials poussés.')
    else:
        messages.warning(request,
            f'⚠️ Projet créé mais Jenkins indisponible. '
            f'Relancez depuis la page du projet.')

    return job_created, creds_ok


@login_required
def project_list(request):
    projects = Project.objects.filter(owner=request.user) \
        if request.user.role != 'admin' else Project.objects.all()
    return render(request, 'projects/list.html', {'projects': projects})


@login_required
def project_create(request):
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.owner = request.user
            project.save()
            _setup_jenkins(project, request)
            return redirect('project_detail', pk=project.pk)
    else:
        form = ProjectForm()
    return render(request, 'projects/form.html', {
        'form': form, 'action': 'Créer',
        'title': 'Nouveau projet',
        'stage_list': STAGE_LIST,
        'cred_list': CRED_LIST})


@login_required
def project_edit(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            project = form.save()
            _setup_jenkins(project, request)
            return redirect('project_detail', pk=project.pk)
    else:
        form = ProjectForm(instance=project)
    return render(request, 'projects/form.html', {
        'form': form, 'action': 'Modifier',
        'title': f'Modifier {project.name}',
        'project': project,
        'stage_list': STAGE_LIST,
        'cred_list': CRED_LIST})


@login_required
def project_detail(request, pk):
    project     = get_object_or_404(Project, pk=pk)
    deployments = project.deployments.order_by('-started_at')[:15]
    jenkinsfile = generate_jenkinsfile(project)
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
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        deployment = Deployment.objects.create(
            project=project, status='PENDING',
            triggered_by=request.user)
        for i, name in enumerate(STAGE_LIST):
            DeploymentStage.objects.create(
                deployment=deployment, name=name, order=i)

        client = JenkinsClient()
        try:
            result = client.trigger_build(project.jenkins_job_name)

            # Wait for Jenkins to start the build then get build number
            time.sleep(4)
            last_build = client.get_last_build_number(project.jenkins_job_name)

            deployment.status = 'RUNNING'
            if last_build:
                deployment.jenkins_build_number = last_build
                deployment.jenkins_build_url = (
                    f"{client.url}/job/{project.jenkins_job_name}/{last_build}/")
                deployment.save(update_fields=[
                    'status', 'jenkins_build_number', 'jenkins_build_url'])
            else:
                deployment.save(update_fields=['status'])

            if result.get('mock'):
                messages.info(request, 'Jenkins non connecté — déploiement simulé.')
            else:
                messages.success(request,
                    f'🚀 Pipeline déclenché! Déploiement #{deployment.pk} '
                    f'— Build Jenkins #{last_build}')

        except Exception as e:
            deployment.mark_finished('FAILED', str(e))
            messages.error(request, f'Erreur Jenkins: {e}')

        return redirect('deployment_detail', pk=deployment.pk)
    return redirect('project_detail', pk=pk)


@login_required
def project_push_credentials(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        cred_mgr = JenkinsCredentialsManager()
        results  = cred_mgr.push_all_credentials(project)
        success  = sum(1 for v in results.values() if v)
        total    = len(results)
        messages.success(request,
            f'Credentials mis à jour: {success}/{total} poussés vers Jenkins.')
    return redirect('project_detail', pk=pk)


@login_required
def jenkinsfile_download(request, pk):
    project  = get_object_or_404(Project, pk=pk)
    content  = generate_jenkinsfile(project)
    response = HttpResponse(content, content_type='text/plain')
    response['Content-Disposition'] = 'attachment; filename="Jenkinsfile"'
    return response
