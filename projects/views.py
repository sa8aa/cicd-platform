from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse

from .models import Project
from .forms import ProjectForm
from deployments.models import Deployment, DeploymentStage
from integrations.jenkins_client import JenkinsClient
from integrations.jenkinsfile_generator import generate_jenkinsfile
from integrations.infra_generator import (
    generate_k8s_deployment,
    generate_k8s_service,
    generate_cloudformation,
)


@login_required
def project_list(request):
    projects = Project.objects.filter(owner=request.user) \
        if request.user.role != 'admin' else Project.objects.all()
    return render(request, 'projects/list.html', {'projects': projects})


STAGE_LIST = [
    'Checkout', 'Install Dependencies', 'Run Tests',
    'Build & Push Images', 'Provision Infra', 'Deploy to k3s',
]


def _push_credentials(form, client: JenkinsClient) -> dict:
    """Extract credentials from form and push them to Jenkins. Returns results dict."""
    creds = {
        'dockerhub_username':   form.cleaned_data.get('dockerhub_username') or '',
        'dockerhub_password':   form.cleaned_data.get('dockerhub_password') or '',
        'aws_access_key_id':    form.cleaned_data.get('aws_access_key_id') or '',
        'aws_secret_access_key':form.cleaned_data.get('aws_secret_access_key') or '',
        'aws_session_token':    form.cleaned_data.get('aws_session_token') or '',
        'ec2_ssh_key':          form.cleaned_data.get('ec2_ssh_key_pem') or '',
    }
    # Only push credentials that were actually filled in
    filled = {k: v for k, v in creds.items() if v.strip()}
    if not filled:
        return {}
    return client.push_all_credentials(filled)


@login_required
def project_create(request):
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.owner = request.user
            project.save()

            client = JenkinsClient()
            cred_results = {}
            jenkins_ok   = False

            if client.is_connected():
                # 1. Push credentials to Jenkins
                cred_results = _push_credentials(form, client)
                if cred_results:
                    all_ok = all(cred_results.values())
                    if all_ok:
                        messages.success(request,
                            f'✅ {len(cred_results)} credential(s) configuré(s) dans Jenkins.')
                    else:
                        failed = [k for k, v in cred_results.items() if not v]
                        messages.warning(request,
                            f'⚠️ Credentials partiellement configurés. Échec: {", ".join(failed)}')

                # 2. Generate Jenkinsfile and create job
                jenkinsfile = generate_jenkinsfile(project)
                jenkins_ok = client.create_or_update_job(
                    project.jenkins_job_name, jenkinsfile,
                    description=project.description)

                if jenkins_ok:
                    project.jenkins_created = True
                    project.save(update_fields=['jenkins_created'])
                    messages.success(request,
                        f'Projet «{project.name}» créé et job Jenkins configuré ✅')
                else:
                    messages.warning(request,
                        'Projet créé mais la création du job Jenkins a échoué.')
            else:
                messages.warning(request,
                    'Projet créé. Jenkins non connecté — credentials et job non configurés.')

            return redirect('project_detail', pk=project.pk)
    else:
        form = ProjectForm()
    return render(request, 'projects/form.html', {
        'form': form, 'action': 'Créer', 'title': 'Nouveau projet',
        'stage_list': STAGE_LIST,
    })


@login_required
def project_edit(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            project = form.save()
            client = JenkinsClient()
            if client.is_connected():
                # Re-push any updated credentials
                cred_results = _push_credentials(form, client)
                if cred_results:
                    messages.info(request,
                        f'{len(cred_results)} credential(s) mis à jour dans Jenkins.')
                # Regenerate and update job
                jenkinsfile = generate_jenkinsfile(project)
                client.create_or_update_job(project.jenkins_job_name,
                                             jenkinsfile, project.description)
            messages.success(request, f'Projet «{project.name}» mis à jour ✅')
            return redirect('project_detail', pk=project.pk)
    else:
        form = ProjectForm(instance=project)
    return render(request, 'projects/form.html', {
        'form': form, 'action': 'Modifier',
        'title': f'Modifier {project.name}',
        'project': project, 'stage_list': STAGE_LIST,
    })


@login_required
def project_detail(request, pk):
    project     = get_object_or_404(Project, pk=pk)
    deployments = project.deployments.order_by('-started_at')[:15]
    jenkinsfile = generate_jenkinsfile(project)

    # Generate manifest previews for the detail page
    k8s_dep_yaml = generate_k8s_deployment(project) if project.generate_manifests else None
    k8s_svc_yaml = generate_k8s_service(project)    if project.generate_manifests else None
    cf_yaml      = generate_cloudformation(project)  if project.generate_manifests else None

    return render(request, 'projects/detail.html', {
        'project':      project,
        'deployments':  deployments,
        'jenkinsfile':  jenkinsfile,
        'k8s_dep_yaml': k8s_dep_yaml,
        'k8s_svc_yaml': k8s_svc_yaml,
        'cf_yaml':      cf_yaml,
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
        client     = JenkinsClient()
        deployment = Deployment.objects.create(
            project=project, status='PENDING', triggered_by=request.user)
        for i, name in enumerate(STAGE_LIST):
            DeploymentStage.objects.create(
                deployment=deployment, name=name, order=i)
        try:
            result = client.trigger_build(project.jenkins_job_name)
            deployment.status = 'RUNNING'
            deployment.save(update_fields=['status'])
            if result.get('mock'):
                messages.info(request, 'Jenkins non connecté — déploiement simulé.')
            else:
                messages.success(request,
                    f'Pipeline déclenché ! Suivez le déploiement #{deployment.pk}')
        except Exception as e:
            deployment.mark_finished('FAILED', str(e))
            messages.error(request, f'Erreur Jenkins: {e}')
        return redirect('deployment_detail', pk=deployment.pk)
    return redirect('project_detail', pk=pk)


@login_required
def jenkinsfile_download(request, pk):
    project = get_object_or_404(Project, pk=pk)
    content = generate_jenkinsfile(project)
    response = HttpResponse(content, content_type='text/plain')
    response['Content-Disposition'] = 'attachment; filename="Jenkinsfile"'
    return response


@login_required
def manifest_download(request, pk, manifest_type):
    """Download a generated manifest file: k8s-deployment, k8s-service, cloudformation."""
    project = get_object_or_404(Project, pk=pk)
    if manifest_type == 'k8s-deployment':
        content  = generate_k8s_deployment(project)
        filename = 'deployment.yaml'
    elif manifest_type == 'k8s-service':
        content  = generate_k8s_service(project)
        filename = 'service.yaml'
    elif manifest_type == 'cloudformation':
        content  = generate_cloudformation(project)
        filename = 'infra-stack.yaml'
    else:
        return HttpResponse('Not found', status=404)
    response = HttpResponse(content, content_type='text/plain')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
