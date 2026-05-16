from django.urls import path
from . import views

urlpatterns = [
    path('<int:pk>/',        views.deployment_detail, name='deployment_detail'),
    path('<int:pk>/cancel/', views.deployment_cancel, name='deployment_cancel'),
    path('<int:pk>/stream/',  views.stream_logs,      name='deployment_stream'),
    path('notifications/',   views.notifications_view, name='notifications'),
]
