from django import forms
from .models import Project


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = [
            # Identity
            'name', 'description',
            # Git
            'repo_url', 'branch',
            # Cloud
            'cloud_provider', 'environment',
            # AWS Config
            'aws_region', 'aws_account_id', 'aws_key_name', 'cf_stack_name',
            # AWS Credentials
            'aws_access_key_id', 'aws_secret_access_key', 'aws_session_token',
            # EC2 SSH Key
            'ec2_private_key',
            # Docker
            'dockerhub_username', 'dockerhub_token', 'image_name',
            # Paths
            'k8s_deployment_file', 'k8s_service_file',
            'cf_template_file', 'app_port',
        ]
        widgets = {
            # Identity
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'ex: my-django-app'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2}),
            # Git
            'repo_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://github.com/user/repo.git'}),
            'branch': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'main'}),
            # Cloud
            'cloud_provider': forms.Select(attrs={'class': 'form-select'}),
            'environment':    forms.Select(attrs={'class': 'form-select'}),
            'aws_region':     forms.Select(attrs={'class': 'form-select'}),
            'aws_account_id': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': '271744664756'}),
            'aws_key_name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'vockey'}),
            'cf_stack_name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'my-app-infra'}),
            # AWS Credentials
            'aws_access_key_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'ASIAT6RJ6QS2E5MTLZXU'}),
            'aws_secret_access_key': forms.PasswordInput(attrs={
                'class': 'form-control',
                'placeholder': 'Votre AWS Secret Access Key'},
                render_value=True),
            'aws_session_token': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3,
                'placeholder': 'FwoGZXIv... (AWS Session Token)'}),
            # EC2 SSH
            'ec2_private_key': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 5,
                'placeholder': '-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----',
                'style': 'font-family: monospace; font-size: 0.8rem'}),
            # Docker
            'dockerhub_username': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'sa8aa'}),
            'dockerhub_token': forms.PasswordInput(attrs={
                'class': 'form-control',
                'placeholder': 'DockerHub Access Token'},
                render_value=True),
            'image_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'sa8aa/my-django-app'}),
            # Paths
            'k8s_deployment_file': forms.TextInput(attrs={'class': 'form-control'}),
            'k8s_service_file':    forms.TextInput(attrs={'class': 'form-control'}),
            'cf_template_file':    forms.TextInput(attrs={'class': 'form-control'}),
            'app_port': forms.NumberInput(attrs={
                'class': 'form-control', 'placeholder': '30080'}),
        }
        labels = {
            'name':                  'Nom du projet',
            'description':           'Description',
            'repo_url':              'URL du dépôt GitHub',
            'branch':                'Branche',
            'cloud_provider':        'Cloud Provider',
            'environment':           'Environnement cible',
            'aws_region':            'Région AWS',
            'aws_account_id':        'AWS Account ID',
            'aws_key_name':          'Nom du Key Pair EC2',
            'cf_stack_name':         'Nom du Stack CloudFormation',
            'aws_access_key_id':     'AWS Access Key ID',
            'aws_secret_access_key': 'AWS Secret Access Key',
            'aws_session_token':     'AWS Session Token',
            'ec2_private_key':       'Clé privée EC2 (.pem)',
            'dockerhub_username':    'Username DockerHub',
            'dockerhub_token':       'DockerHub Access Token',
            'image_name':            "Nom de l'image Docker",
            'k8s_deployment_file':   'Chemin deployment.yaml',
            'k8s_service_file':      'Chemin service.yaml',
            'cf_template_file':      'Chemin template CloudFormation',
            'app_port':              'Port applicatif (NodePort)',
        }

    def clean_app_port(self):
        port = self.cleaned_data.get('app_port')
        if port and not (30000 <= port <= 32767):
            raise forms.ValidationError(
                'Le NodePort doit être entre 30000 et 32767.')
        return port
