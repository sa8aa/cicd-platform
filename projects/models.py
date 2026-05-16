import json
from django.db import models
from core.models import User


class Project(models.Model):
    CLOUD_CHOICES = [
        ('AWS',   'Amazon Web Services'),
        ('Azure', 'Microsoft Azure'),
        ('GCP',   'Google Cloud Platform'),
    ]
    ENV_CHOICES = [
        ('dev',     'Développement'),
        ('staging', 'Staging'),
        ('prod',    'Production'),
    ]
    AWS_REGIONS = [
        ('us-east-1',      'US East (N. Virginia)'),
        ('us-west-2',      'US West (Oregon)'),
        ('eu-west-1',      'Europe (Ireland)'),
        ('eu-central-1',   'Europe (Frankfurt)'),
        ('ap-southeast-1', 'Asia Pacific (Singapore)'),
        ('ap-northeast-1', 'Asia Pacific (Tokyo)'),
    ]
    EC2_TYPES = [
        ('t3.micro',  't3.micro  (1 vCPU, 1 GB)'),
        ('t3.small',  't3.small  (2 vCPU, 2 GB)'),
        ('t3.medium', 't3.medium (2 vCPU, 4 GB)'),
        ('t3.large',  't3.large  (2 vCPU, 8 GB)'),
    ]

    # ── Identity ──────────────────────────────────────────────────────────
    name        = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    owner       = models.ForeignKey(User, on_delete=models.CASCADE,
                                    related_name='projects')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    # ── Git ───────────────────────────────────────────────────────────────
    repo_url    = models.URLField(help_text='https://github.com/user/repo.git')
    branch      = models.CharField(max_length=100, default='main')

    # ── Cloud ─────────────────────────────────────────────────────────────
    cloud_provider = models.CharField(max_length=10, choices=CLOUD_CHOICES, default='AWS')
    environment    = models.CharField(max_length=10, choices=ENV_CHOICES, default='staging')

    # ── AWS config ────────────────────────────────────────────────────────
    aws_region     = models.CharField(max_length=30, choices=AWS_REGIONS,
                                      default='us-east-1', blank=True)
    aws_account_id = models.CharField(max_length=20, blank=True,
                                      help_text='12-digit AWS account ID')
    aws_key_name   = models.CharField(max_length=100, blank=True,
                                      help_text='EC2 Key Pair name (ex: vockey)')
    cf_stack_name  = models.CharField(max_length=100, blank=True,
                                      help_text='CloudFormation stack name')

    # ── Docker / ECR ──────────────────────────────────────────────────────
    dockerhub_username = models.CharField(max_length=100, blank=True)
    image_name         = models.CharField(max_length=200, blank=True,
                                          help_text='dockerhub_user/image-name')

    # ── Jenkins ───────────────────────────────────────────────────────────
    jenkins_job_name = models.CharField(max_length=200, blank=True)
    jenkins_created  = models.BooleanField(default=False)

    # ── K8s manifest paths (kept for backward compat, now auto-generated) ─
    k8s_deployment_file = models.CharField(max_length=200, default='k8s/deployment.yaml')
    k8s_service_file    = models.CharField(max_length=200, default='k8s/service.yaml')
    cf_template_file    = models.CharField(max_length=200,
                                           default='cloudformation/infra-stack.yaml')
    app_port            = models.IntegerField(default=30080,
                                              help_text='NodePort exposed by k3s')

    # ── Infra config (NEW) — used to generate manifests ───────────────────
    container_port       = models.IntegerField(default=8000,
                                               help_text='Port your app listens on inside the container')
    ec2_instance_type    = models.CharField(max_length=20, choices=EC2_TYPES,
                                            default='t3.small', blank=True)
    k8s_replicas         = models.IntegerField(default=1,
                                               help_text='Number of pod replicas')
    k8s_cpu_request      = models.CharField(max_length=20, default='100m', blank=True)
    k8s_memory_request   = models.CharField(max_length=20, default='128Mi', blank=True)
    k8s_cpu_limit        = models.CharField(max_length=20, default='500m', blank=True)
    k8s_memory_limit     = models.CharField(max_length=20, default='512Mi', blank=True)
    k8s_env_vars         = models.TextField(blank=True,
                                            help_text='KEY=VALUE pairs, one per line')

    # ── Manifest generation mode ──────────────────────────────────────────
    # True  → platform generates manifests and injects them via pipeline
    # False → manifests exist in the repo at the paths above
    generate_manifests   = models.BooleanField(default=True,
                                               help_text='Auto-generate k8s + CF manifests')

    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.jenkins_job_name:
            self.jenkins_job_name = self.name.lower().replace(' ', '-').replace('_', '-')
        if not self.image_name and self.dockerhub_username:
            self.image_name = f"{self.dockerhub_username}/{self.jenkins_job_name}"
        super().save(*args, **kwargs)

    @property
    def ecr_repo(self):
        if self.aws_account_id and self.aws_region:
            return (f"{self.aws_account_id}.dkr.ecr.{self.aws_region}"
                    f".amazonaws.com/{self.jenkins_job_name}")
        return ''

    def get_last_deployment(self):
        return self.deployments.order_by('-started_at').first()

    def get_success_rate(self):
        total = self.deployments.count()
        if not total:
            return 0
        success = self.deployments.filter(status='SUCCESS').count()
        return round((success / total) * 100, 1)

    def get_status_color(self):
        last = self.get_last_deployment()
        if not last:
            return 'secondary'
        return {
            'SUCCESS':   'success',
            'FAILED':    'danger',
            'RUNNING':   'primary',
            'PENDING':   'warning',
            'CANCELLED': 'secondary',
        }.get(last.status, 'secondary')

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-created_at']
