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

    # ── Identity ──────────────────────────────────────────────────────
    name        = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    owner       = models.ForeignKey(User, on_delete=models.CASCADE,
                                    related_name='projects')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    # ── Git ───────────────────────────────────────────────────────────
    repo_url = models.URLField(help_text='https://github.com/user/repo.git')
    branch   = models.CharField(max_length=100, default='main')

    # ── Cloud ─────────────────────────────────────────────────────────
    cloud_provider = models.CharField(max_length=10, choices=CLOUD_CHOICES,
                                       default='AWS')
    environment    = models.CharField(max_length=10, choices=ENV_CHOICES,
                                       default='staging')

    # ── AWS config ────────────────────────────────────────────────────
    aws_region     = models.CharField(max_length=30, choices=AWS_REGIONS,
                                       default='us-east-1', blank=True)
    aws_account_id = models.CharField(max_length=20, blank=True)
    aws_key_name   = models.CharField(max_length=100, blank=True)
    cf_stack_name  = models.CharField(max_length=100, blank=True)

    # ── AWS Credentials (stored encrypted) ────────────────────────────
    aws_access_key_id     = models.CharField(max_length=100, blank=True,
        help_text='AWS Access Key ID (ex: ASIAT6RJ6QS2...)')
    aws_secret_access_key = models.CharField(max_length=200, blank=True,
        help_text='AWS Secret Access Key')
    aws_session_token     = models.TextField(blank=True,
        help_text='AWS Session Token (Learner Lab uniquement)')
    ec2_private_key       = models.TextField(blank=True,
        help_text='Contenu du fichier .pem (clé privée SSH EC2)')

    # ── Docker / ECR ──────────────────────────────────────────────────
    dockerhub_username = models.CharField(max_length=100, blank=True)
    dockerhub_token    = models.CharField(max_length=200, blank=True,
        help_text='DockerHub Access Token (pas le mot de passe)')
    image_name         = models.CharField(max_length=200, blank=True)

    # ── Jenkins ───────────────────────────────────────────────────────
    jenkins_job_name        = models.CharField(max_length=200, blank=True)
    jenkins_created         = models.BooleanField(default=False)
    jenkins_creds_created   = models.BooleanField(default=False)

    # ── K8s / CF paths ────────────────────────────────────────────────
    k8s_deployment_file = models.CharField(max_length=200,
                                            default='k8s/deployment.yaml')
    k8s_service_file    = models.CharField(max_length=200,
                                            default='k8s/service.yaml')
    cf_template_file    = models.CharField(max_length=200,
                                            default='cloudformation/infra-stack.yaml')
    app_port            = models.IntegerField(default=30080)
    is_active           = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.jenkins_job_name:
            self.jenkins_job_name = (self.name.lower()
                                     .replace(' ', '-')
                                     .replace('_', '-'))
        if not self.image_name and self.dockerhub_username:
            self.image_name = f"{self.dockerhub_username}/{self.jenkins_job_name}"
        super().save(*args, **kwargs)

    @property
    def ecr_repo(self):
        if self.aws_account_id and self.aws_region:
            return (f"{self.aws_account_id}.dkr.ecr.{self.aws_region}"
                    f".amazonaws.com/{self.jenkins_job_name}")
        return ''

    # Credential IDs used in Jenkinsfile
    @property
    def cred_id_dockerhub(self):
        return f"{self.jenkins_job_name}-dockerhub-creds"

    @property
    def cred_id_aws(self):
        return f"{self.jenkins_job_name}-aws-credentials"

    @property
    def cred_id_aws_token(self):
        return f"{self.jenkins_job_name}-aws-session-token"

    @property
    def cred_id_ssh(self):
        return f"{self.jenkins_job_name}-ec2-ssh-key"

    def get_last_deployment(self):
        return self.deployments.order_by('-started_at').first()

    def get_success_rate(self):
        total = self.deployments.count()
        if not total:
            return 0
        return round(self.deployments.filter(
            status='SUCCESS').count() / total * 100, 1)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-created_at']
