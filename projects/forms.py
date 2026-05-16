from django import forms
from .models import Project


class ProjectForm(forms.ModelForm):
    """
    Main project form.
    Extra fields (credentials, infra) are NOT on the model —
    they are handled in the view and sent to Jenkins/generator directly.
    """

    # ── Credentials (not stored in DB — pushed to Jenkins only) ───────────
    dockerhub_password = forms.CharField(
        label='Mot de passe / Token DockerHub',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 'placeholder': 'dckr_pat_xxxx',
            'autocomplete': 'new-password',
        }),
        required=False,
        help_text='Votre token DockerHub (non stocké en base).',
    )
    aws_access_key_id = forms.CharField(
        label='AWS Access Key ID',
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'AKIA…',
        }),
        required=False,
    )
    aws_secret_access_key = forms.CharField(
        label='AWS Secret Access Key',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 'autocomplete': 'new-password',
        }),
        required=False,
    )
    aws_session_token = forms.CharField(
        label='AWS Session Token',
        widget=forms.Textarea(attrs={
            'class': 'form-control', 'rows': 2,
            'placeholder': 'Optionnel — requis si vous utilisez un compte Academy/temporary',
        }),
        required=False,
    )
    ec2_ssh_key_pem = forms.CharField(
        label='Clé SSH privée EC2 (PEM)',
        widget=forms.Textarea(attrs={
            'class': 'form-control font-monospace', 'rows': 5,
            'placeholder': '-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----',
            'style': 'font-size:.75rem',
        }),
        required=False,
        help_text='Collez le contenu de votre fichier .pem. Non stocké en base.',
    )

    class Meta:
        model = Project
        fields = [
            # Identity
            'name', 'description',
            # Git
            'repo_url', 'branch',
            # Cloud
            'cloud_provider', 'environment',
            'aws_region', 'aws_account_id', 'aws_key_name', 'cf_stack_name',
            # Docker
            'dockerhub_username', 'image_name',
            # Jenkins
            'jenkins_job_name',
            # Infra generator
            'generate_manifests',
            'container_port', 'ec2_instance_type',
            'k8s_replicas',
            'k8s_cpu_request', 'k8s_memory_request',
            'k8s_cpu_limit', 'k8s_memory_limit',
            'k8s_env_vars',
            # Paths (shown only when generate_manifests=False)
            'k8s_deployment_file', 'k8s_service_file', 'cf_template_file',
            'app_port',
        ]
        widgets = {
            'name':               forms.TextInput(attrs={'class': 'form-control'}),
            'description':        forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'repo_url':           forms.URLInput(attrs={'class': 'form-control',
                                                        'placeholder': 'https://github.com/user/repo.git'}),
            'branch':             forms.TextInput(attrs={'class': 'form-control'}),
            'cloud_provider':     forms.Select(attrs={'class': 'form-select'}),
            'environment':        forms.Select(attrs={'class': 'form-select'}),
            'aws_region':         forms.Select(attrs={'class': 'form-select'}),
            'aws_account_id':     forms.TextInput(attrs={'class': 'form-control',
                                                         'placeholder': '123456789012',
                                                         'maxlength': '12', 'pattern': '[0-9]{12}'}),
            'aws_key_name':       forms.TextInput(attrs={'class': 'form-control',
                                                         'placeholder': 'vockey'}),
            'cf_stack_name':      forms.TextInput(attrs={'class': 'form-control',
                                                         'placeholder': 'my-app-infra'}),
            'dockerhub_username': forms.TextInput(attrs={'class': 'form-control'}),
            'image_name':         forms.TextInput(attrs={'class': 'form-control',
                                                         'placeholder': 'user/my-app'}),
            'jenkins_job_name':   forms.TextInput(attrs={'class': 'form-control',
                                                         'placeholder': 'Auto-généré si vide'}),
            'generate_manifests': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'container_port':     forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 65535}),
            'ec2_instance_type':  forms.Select(attrs={'class': 'form-select'}),
            'k8s_replicas':       forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 10}),
            'k8s_cpu_request':    forms.TextInput(attrs={'class': 'form-control', 'placeholder': '100m'}),
            'k8s_memory_request': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '128Mi'}),
            'k8s_cpu_limit':      forms.TextInput(attrs={'class': 'form-control', 'placeholder': '500m'}),
            'k8s_memory_limit':   forms.TextInput(attrs={'class': 'form-control', 'placeholder': '512Mi'}),
            'k8s_env_vars':       forms.Textarea(attrs={'class': 'form-control font-monospace',
                                                        'rows': 3,
                                                        'placeholder': 'DJANGO_SETTINGS_MODULE=myapp.settings\nDEBUG=False'}),
            'k8s_deployment_file': forms.TextInput(attrs={'class': 'form-control'}),
            'k8s_service_file':    forms.TextInput(attrs={'class': 'form-control'}),
            'cf_template_file':    forms.TextInput(attrs={'class': 'form-control'}),
            'app_port':            forms.NumberInput(attrs={'class': 'form-control', 'min': 30000, 'max': 32767}),
        }

    def clean_aws_account_id(self):
        v = self.cleaned_data.get('aws_account_id', '').strip()
        if v and (not v.isdigit() or len(v) != 12):
            raise forms.ValidationError('L\'AWS Account ID doit contenir exactement 12 chiffres.')
        return v

    def clean_app_port(self):
        v = self.cleaned_data.get('app_port')
        if v and not (30000 <= v <= 32767):
            raise forms.ValidationError('Le NodePort doit être entre 30000 et 32767.')
        return v

    def clean_repo_url(self):
        v = self.cleaned_data.get('repo_url', '').strip()
        if v and not (v.startswith('https://github.com') or v.endswith('.git')):
            raise forms.ValidationError(
                'L\'URL doit être une URL GitHub valide (https://github.com/…).')
        return v
