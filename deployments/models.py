from django.db import models
from django.utils import timezone
from core.models import User
from projects.models import Project


class Deployment(models.Model):
    STATUS_CHOICES = [
        ('PENDING',   'En attente'),
        ('RUNNING',   'En cours'),
        ('SUCCESS',   'Réussi'),
        ('FAILED',    'Échoué'),
        ('CANCELLED', 'Annulé'),
    ]

    project              = models.ForeignKey(Project, on_delete=models.CASCADE,
                                              related_name='deployments')
    status               = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                             default='PENDING')
    triggered_by         = models.ForeignKey(User, on_delete=models.SET_NULL,
                                              null=True, related_name='deployments')
    started_at           = models.DateTimeField(default=timezone.now)
    finished_at          = models.DateTimeField(null=True, blank=True)
    duration             = models.DurationField(null=True, blank=True)
    commit_sha           = models.CharField(max_length=40, blank=True)
    jenkins_build_number = models.IntegerField(null=True, blank=True)
    jenkins_build_url    = models.URLField(blank=True)
    error_message        = models.TextField(blank=True)

    def mark_finished(self, status, error=''):
        self.status       = status
        self.finished_at  = timezone.now()
        self.error_message = error
        if self.started_at:
            self.duration = self.finished_at - self.started_at
        self.save()
        # Send notification
        Notification.objects.create(
            user=self.project.owner,
            deployment=self,
            type=status,
            message=self._notification_message(status),
        )

    def _notification_message(self, status):
        msgs = {
            'SUCCESS':   f"✅ Déploiement #{self.pk} de «{self.project.name}» réussi"
                         f" en {self.duration}.",
            'FAILED':    f"❌ Déploiement #{self.pk} de «{self.project.name}» a échoué."
                         f" Erreur: {self.error_message[:80]}",
            'RUNNING':   f"🚀 Déploiement #{self.pk} de «{self.project.name}» démarré.",
            'CANCELLED': f"⛔ Déploiement #{self.pk} de «{self.project.name}» annulé.",
        }
        return msgs.get(status, f"Déploiement #{self.pk} mis à jour: {status}")

    def get_app_url(self):
        """Returns the app URL once deployed (from EC2 IP stored in logs)."""
        ip_log = self.stages.filter(name='Deploy to k3s',
                                     status='SUCCESS').first()
        if ip_log:
            ec2 = self.logs.filter(message__startswith='EC2_IP:').first()
            if ec2:
                ip = ec2.message.replace('EC2_IP:', '').strip()
                return f"http://{ip}:{self.project.app_port}"
        return ''

    def __str__(self):
        return f"#{self.pk} {self.project.name} [{self.status}]"

    class Meta:
        ordering = ['-started_at']


class DeploymentStage(models.Model):
    """Mirrors the 5 Jenkins stages from the Jenkinsfile."""
    STATUS_CHOICES = [
        ('PENDING', 'En attente'),
        ('RUNNING', 'En cours'),
        ('SUCCESS', 'Réussi'),
        ('FAILED',  'Échoué'),
        ('SKIPPED', 'Ignoré'),
    ]
    STAGE_CHOICES = [
        ('Checkout',           'Checkout'),
        ('Install Dependencies','Install Dependencies'),
        ('Run Tests',          'Run Tests'),
        ('Build & Push Images','Build & Push Images'),
        ('Provision Infra',    'Provision Infra'),
        ('Deploy to k3s',      'Deploy to k3s'),
    ]

    deployment = models.ForeignKey(Deployment, on_delete=models.CASCADE,
                                    related_name='stages')
    name       = models.CharField(max_length=100, choices=STAGE_CHOICES)
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                   default='PENDING')
    order      = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at= models.DateTimeField(null=True, blank=True)
    duration   = models.DurationField(null=True, blank=True)

    def __str__(self):
        return f"{self.deployment} → {self.name} [{self.status}]"

    class Meta:
        ordering = ['order']


class DeploymentLog(models.Model):
    LEVEL_CHOICES = [
        ('INFO',    'Info'),
        ('WARNING', 'Warning'),
        ('ERROR',   'Error'),
        ('SUCCESS', 'Success'),
    ]
    deployment = models.ForeignKey(Deployment, on_delete=models.CASCADE,
                                    related_name='logs')
    stage      = models.ForeignKey(DeploymentStage, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='logs')
    level      = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='INFO')
    message    = models.TextField()
    timestamp  = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"[{self.level}] {self.message[:60]}"

    class Meta:
        ordering = ['timestamp']


class Notification(models.Model):
    TYPE_CHOICES = [
        ('SUCCESS',   'Succès'),
        ('FAILED',    'Échec'),
        ('RUNNING',   'En cours'),
        ('CANCELLED', 'Annulé'),
        ('INFO',      'Info'),
    ]
    user       = models.ForeignKey(User, on_delete=models.CASCADE,
                                    related_name='notifications')
    deployment = models.ForeignKey(Deployment, on_delete=models.SET_NULL,
                                    null=True, blank=True,
                                    related_name='notifications')
    type       = models.CharField(max_length=20, choices=TYPE_CHOICES)
    message    = models.TextField()
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"[{self.type}] {self.user.username}: {self.message[:50]}"

    class Meta:
        ordering = ['-created_at']
