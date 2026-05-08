from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProjectViewSet, DeploymentViewSet, jenkins_webhook

router = DefaultRouter()
router.register(r'projects',    ProjectViewSet,    basename='api-project')
router.register(r'deployments', DeploymentViewSet, basename='api-deployment')

urlpatterns = [
    path('', include(router.urls)),
    path('webhook/jenkins/', jenkins_webhook, name='jenkins_webhook'),
]
