from django import forms
from .models import Project


class ProjectForm(forms.ModelForm):
    """
    The main form the user fills to register a project.
    Each section maps to a pipeline stage.
    """
    class Meta:
        model = Project
        fields = [
            # Identity
            'name', 'description',
            # Git
            'repo_url', 'branch',
            # Cloud
            'cloud_provider', 'environment',
            # AWS
            'aws_region', 'aws_account_id', 'aws_key_name', 'cf_stack_name',
            # Docker
            'dockerhub_username', 'image_name',
            # K8s paths
            'k8s_deployment_file', 'k8s_service_file',
            'cf_template_file', 'app_port',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'ex: my-django-app'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2,
                'placeholder': 'Description courte du projet'}),
            'repo_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://github.com/user/repo.git'}),
            'branch': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'main'}),
            'cloud_provider': forms.Select(attrs={'class': 'form-select',
                'id': 'id_cloud_provider'}),
            'environment': forms.Select(attrs={'class': 'form-select'}),
            'aws_region': forms.Select(attrs={'class': 'form-select'}),
            'aws_account_id': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': '271744664756'}),
            'aws_key_name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'vockey'}),
            'cf_stack_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'my-app-infra'}),
            'dockerhub_username': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'sa8aa'}),
            'image_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'sa8aa/my-django-app'}),
            'k8s_deployment_file': forms.TextInput(attrs={'class': 'form-control'}),
            'k8s_service_file': forms.TextInput(attrs={'class': 'form-control'}),
            'cf_template_file': forms.TextInput(attrs={'class': 'form-control'}),
            'app_port': forms.NumberInput(attrs={
                'class': 'form-control', 'placeholder': '30080'}),
        }
        labels = {
            'name':               'Nom du projet',
            'description':        'Description',
            'repo_url':           'URL du dépôt GitHub',
            'branch':             'Branche',
            'cloud_provider':     'Cloud Provider',
            'environment':        'Environnement cible',
            'aws_region':         'Région AWS',
            'aws_account_id':     'AWS Account ID',
            'aws_key_name':       'Nom du Key Pair EC2',
            'cf_stack_name':      'Nom du Stack CloudFormation',
            'dockerhub_username': 'Username DockerHub',
            'image_name':         'Nom de l\'image Docker',
            'k8s_deployment_file':'Chemin deployment.yaml',
            'k8s_service_file':   'Chemin service.yaml',
            'cf_template_file':   'Chemin template CloudFormation',
            'app_port':           'Port applicatif (NodePort)',
        }
        help_texts = {
            'aws_account_id':  'Votre identifiant de compte AWS à 12 chiffres.',
            'aws_key_name':    'Nom de la paire de clés SSH dans AWS (ex: vockey).',
            'cf_stack_name':   'Nom unique pour le stack CloudFormation.',
            'image_name':      'Format: dockerhub_user/nom-image',
            'app_port':        'Port NodePort exposé par k3s (ex: 30080).',
        }

    def clean_aws_account_id(self):
        val = self.cleaned_data.get('aws_account_id', '')
        if val and not val.isdigit():
            raise forms.ValidationError('L\'Account ID doit contenir uniquement des chiffres.')
        return val

    def clean_app_port(self):
        port = self.cleaned_data.get('app_port')
        if port and not (30000 <= port <= 32767):
            raise forms.ValidationError('Le NodePort doit être entre 30000 et 32767.')
        return port
