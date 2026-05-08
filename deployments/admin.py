from django.contrib import admin
from .models import Deployment, DeploymentStage, DeploymentLog, Notification

class StageInline(admin.TabularInline):
    model = DeploymentStage
    extra = 0

class LogInline(admin.TabularInline):
    model = DeploymentLog
    extra = 0
    max_num = 30

@admin.register(Deployment)
class DeploymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'project', 'status', 'started_at', 'duration', 'triggered_by')
    list_filter = ('status',)
    inlines = [StageInline, LogInline]

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'type', 'is_read', 'created_at')
    list_filter = ('type', 'is_read')
