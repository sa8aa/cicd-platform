import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cicd_platform2.settings')
django.setup()

from django.utils import timezone
from datetime import timedelta
import random

from core.models import User
from projects.models import Project
from deployments.models import Deployment, DeploymentStage, DeploymentLog, Notification

# Users
admin = User.objects.create_superuser(
    username='admin', email='admin@pfa.local', password='admin123', role='admin')
devops = User.objects.create_user(
    username='devops1', email='devops@pfa.local', password='devops123', role='devops')
print("Users: admin/admin123  devops1/devops123")

# Projects (mimicking the real pipeline)
projects_data = [
    {
        'name': 'my-django-app',
        'description': 'Application Django déployée sur AWS EC2 avec k3s',
        'repo_url': 'https://github.com/sa8aa/my-djanjo-app.git',
        'branch': 'main',
        'aws_region': 'us-east-1',
        'aws_account_id': '271744664756',
        'aws_key_name': 'vockey',
        'cf_stack_name': 'my-djanjo-app-infra',
        'dockerhub_username': 'sa8aa',
        'image_name': 'sa8aa/my-djanjo-app',
        'jenkins_job_name': 'my-djanjo-app',
        'jenkins_created': True,
        'environment': 'prod',
        'app_port': 30080,
    },
    {
        'name': 'api-backend',
        'description': 'API REST FastAPI sur AWS',
        'repo_url': 'https://github.com/sa8aa/api-backend.git',
        'branch': 'develop',
        'aws_region': 'eu-west-1',
        'aws_account_id': '271744664756',
        'aws_key_name': 'vockey',
        'cf_stack_name': 'api-backend-infra',
        'dockerhub_username': 'sa8aa',
        'image_name': 'sa8aa/api-backend',
        'jenkins_job_name': 'api-backend',
        'jenkins_created': False,
        'environment': 'staging',
        'app_port': 30081,
    },
]

stage_names = ['Checkout', 'Install Dependencies', 'Run Tests',
               'Build & Push Images', 'Provision Infra', 'Deploy to k3s']

for pd in projects_data:
    p = Project.objects.create(owner=devops, **pd)
    # Create sample deployments
    results = ['SUCCESS', 'SUCCESS', 'FAILED', 'SUCCESS', 'SUCCESS']
    for i, st in enumerate(results):
        started = timezone.now() - timedelta(days=len(results)-i-1, hours=random.randint(1,10))
        finished = started + timedelta(minutes=random.randint(8, 25))
        dep = Deployment.objects.create(
            project=p, status=st, triggered_by=devops,
            started_at=started, finished_at=finished,
            duration=finished-started,
            commit_sha=('%06x' % random.randint(0,0xffffff)) + 'a1b2c3d4e5f6',
            jenkins_build_number=i+1,
            error_message='Run Tests failed: AssertionError' if st=='FAILED' else '')
        for j, sname in enumerate(stage_names):
            s_st = 'SUCCESS'
            if st == 'FAILED' and j == 2: s_st = 'FAILED'
            elif st == 'FAILED' and j > 2: s_st = 'SKIPPED'
            DeploymentStage.objects.create(
                deployment=dep, name=sname, status=s_st, order=j,
                duration=timedelta(seconds=random.randint(5,90)))
        logs = [
            ('INFO',    'Pipeline started — build #' + str(i+1)),
            ('INFO',    'Checkout: ' + p.repo_url),
            ('INFO',    'Dependencies installed successfully'),
            ('INFO',    'Running tests...' if st=='SUCCESS' else 'Running tests...'),
        ]
        if st == 'FAILED':
            logs.append(('ERROR', 'Run Tests failed: AssertionError in test_models'))
        else:
            logs += [
                ('INFO',    'Tests passed: 24 passed, 0 failed'),
                ('INFO',    'Docker image built: ' + p.image_name + ':' + str(i+1)),
                ('INFO',    'Pushed to DockerHub and ECR'),
                ('INFO',    'CloudFormation stack: ' + p.cf_stack_name),
                ('INFO',    'EC2_IP:54.23.' + str(random.randint(100,200)) + '.10'),
                ('SUCCESS', 'App deployed at http://54.23.x.x:' + str(p.app_port)),
            ]
        for level, msg in logs:
            DeploymentLog.objects.create(deployment=dep, level=level, message=msg)
        Notification.objects.create(
            user=devops, deployment=dep, type=st,
            message=('Deployment #'+str(dep.pk)+' of '+p.name+': '+st))

print("Demo data seeded!")
