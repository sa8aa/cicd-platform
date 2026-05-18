"""REST API + Jenkins webhook endpoint."""
import logging
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import serializers

from projects.models import Project
from deployments.models import Deployment, DeploymentStage, DeploymentLog

logger = logging.getLogger(__name__)

# ── Minimal serializers ────────────────────────────────────────────────────

class DeploymentSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    class Meta:
        model = Deployment
        fields = ('id', 'project', 'project_name', 'status', 'started_at',
                  'finished_at', 'duration', 'commit_sha',
                  'jenkins_build_number', 'error_message')

class StageSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeploymentStage
        fields = ('id', 'name', 'status', 'order', 'duration')

class LogSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeploymentLog
        fields = ('id', 'level', 'message', 'timestamp')

class ProjectSerializer(serializers.ModelSerializer):
    last_status    = serializers.SerializerMethodField()
    success_rate   = serializers.SerializerMethodField()
    class Meta:
        model = Project
        fields = ('id', 'name', 'repo_url', 'branch', 'cloud_provider',
                  'environment', 'jenkins_job_name', 'jenkins_created',
                  'last_status', 'success_rate')

    def get_last_status(self, obj):
        d = obj.get_last_deployment()
        return d.status if d else 'NEVER_RUN'

    def get_success_rate(self, obj):
        return obj.get_success_rate()


# ── ViewSets ───────────────────────────────────────────────────────────────

class ProjectViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProjectSerializer
    def get_queryset(self):
        return Project.objects.filter(owner=self.request.user)

class DeploymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DeploymentSerializer
    def get_queryset(self):
        qs = Deployment.objects.all()
        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs


# ── Jenkins Webhook ────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def jenkins_webhook(request):
    """
    Receives Jenkins Notification Plugin callbacks.
    Updates Deployment status, stages, and logs automatically.
    """
    try:
        data         = request.data
        job_name     = data.get('name', '')
        build_data   = data.get('build', {})
        build_number = build_data.get('number')
        phase        = build_data.get('phase', '').upper()
        result       = build_data.get('status', '').upper()
        full_url     = build_data.get('full_url', '')
        scm          = build_data.get('scm', {})
        commit_sha   = scm.get('commit', '')

        logger.info(f"Webhook: {job_name} #{build_number} phase={phase} result={result}")

        # Find matching deployment
        dep = Deployment.objects.filter(
            project__jenkins_job_name=job_name,
            status__in=['PENDING', 'RUNNING'],
        ).order_by('-started_at').first()

        if not dep:
            # Try by build number
            dep = Deployment.objects.filter(
                project__jenkins_job_name=job_name,
                jenkins_build_number=build_number,
            ).first()

        if not dep:
            return Response({'warning': 'No matching deployment.'}, status=200)

        # Update build number and URL
        if build_number:
            dep.jenkins_build_number = build_number
        if full_url:
            dep.jenkins_build_url = full_url
        if commit_sha:
            dep.commit_sha = commit_sha
        dep.save(update_fields=['jenkins_build_number', 'jenkins_build_url',
                                 'commit_sha'])

        # Handle phase
        if phase == 'STARTED':
            dep.status = 'RUNNING'
            dep.save(update_fields=['status'])
            DeploymentLog.objects.create(
                deployment=dep, level='INFO',
                message=f'Pipeline démarré — build #{build_number}')

        elif phase in ('COMPLETED', 'FINALIZED'):
            status_map = {
                'SUCCESS': 'SUCCESS',
                'FAILURE': 'FAILED',
                'ABORTED': 'CANCELLED',
                'UNSTABLE': 'FAILED',
            }
            final = status_map.get(result, 'FAILED')
            error = '' if final == 'SUCCESS' else f'Build Jenkins: {result}'
            dep.mark_finished(final, error)

            # Update stages from Jenkins data if provided
            stages_data = data.get('stages', [])
            for i, s in enumerate(stages_data):
                s_name   = s.get('name', '')
                s_status = 'SUCCESS' if s.get('status') == 'SUCCESS' else 'FAILED'
                DeploymentStage.objects.filter(
                    deployment=dep, name__icontains=s_name.split()[0]
                ).update(status=s_status)

            DeploymentLog.objects.create(
                deployment=dep,
                level='SUCCESS' if final == 'SUCCESS' else 'ERROR',
                message=f'Pipeline terminé: {final}')

        return Response({'status': 'ok', 'deployment_id': dep.id})

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return Response({'error': str(e)}, status=500)


from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from deployments.models import Deployment, DeploymentStage


@login_required
def deployment_status(request, pk):
    """
    AJAX endpoint — returns real-time stage statuses from Jenkins.
    Called every 5s from the deployment detail page.
    """
    try:
        dep = Deployment.objects.get(pk=pk)

        # If finished, just return DB data
        if dep.status in ('SUCCESS', 'FAILED', 'CANCELLED'):
            stages = list(dep.stages.values('name', 'status', 'duration', 'order'))
            return JsonResponse({
                'deployment_status': dep.status,
                'finished': True,
                'stages': stages,
                'duration': str(dep.duration) if dep.duration else '',
            })

        # If running — poll Jenkins for live stage data
        stages_data = []
        if dep.jenkins_build_number:
            from integrations.jenkins_client import JenkinsClient
            client = JenkinsClient()
            jenkins_stages = client.get_build_stages(
                dep.project.jenkins_job_name,
                dep.jenkins_build_number)

            if jenkins_stages:
                for js in jenkins_stages:
                    DeploymentStage.objects.filter(
                        deployment=dep,
                        name__icontains=js['name'].split()[0]
                    ).update(status=js['status'])
                stages_data = jenkins_stages

                # Check if Jenkins build finished
                build_info = client.get_build_info(
                    dep.project.jenkins_job_name,
                    dep.jenkins_build_number)
                result = build_info.get('result')
                if result in ('SUCCESS', 'FAILURE', 'ABORTED'):
                    final = {'SUCCESS': 'SUCCESS',
                             'FAILURE': 'FAILED',
                             'ABORTED': 'CANCELLED'}.get(result, 'FAILED')
                    dep.mark_finished(final)
            else:
                stages_data = list(dep.stages.values(
                    'name', 'status', 'duration', 'order'))
        else:
            stages_data = list(dep.stages.values(
                'name', 'status', 'duration', 'order'))

        return JsonResponse({
            'deployment_status': dep.status,
            'finished': False,
            'stages': stages_data,
            'duration': '',
        })
    except Deployment.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


from django.http import HttpResponse

from django.http import HttpResponse

def metrics_view(request):
    try:
        from prometheus_client import CollectorRegistry, Gauge, generate_latest, CONTENT_TYPE_LATEST
        from projects.models import Project
        from deployments.models import Deployment

        # Crée un registry frais à chaque appel
        registry = CollectorRegistry()

        g1 = Gauge('cicd_projects_total', 'Total projects', registry=registry)
        g1.set(Project.objects.count())

        g2 = Gauge('cicd_deployments_running', 'Running deployments', registry=registry)
        g2.set(Deployment.objects.filter(status='RUNNING').count())

        g3 = Gauge('cicd_deployments_success', 'Successful deployments', registry=registry)
        g3.set(Deployment.objects.filter(status='SUCCESS').count())

        g4 = Gauge('cicd_deployments_failed', 'Failed deployments', registry=registry)
        g4.set(Deployment.objects.filter(status='FAILED').count())

        return HttpResponse(
            generate_latest(registry),
            content_type=CONTENT_TYPE_LATEST)

    except Exception as e:
        return HttpResponse(f"# Error: {e}\n", content_type="text/plain")
