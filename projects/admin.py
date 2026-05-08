from django.contrib import admin
from .models import Project

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'cloud_provider', 'environment',
                    'jenkins_job_name', 'jenkins_created', 'created_at')
    list_filter = ('cloud_provider', 'environment', 'jenkins_created')
    search_fields = ('name', 'repo_url')
