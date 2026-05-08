from django.urls import path
from . import views

urlpatterns = [
    path('',              views.project_list,       name='project_list'),
    path('new/',          views.project_create,     name='project_create'),
    path('<int:pk>/',     views.project_detail,     name='project_detail'),
    path('<int:pk>/edit/',views.project_edit,        name='project_edit'),
    path('<int:pk>/delete/', views.project_delete,  name='project_delete'),
    path('<int:pk>/deploy/', views.project_deploy,  name='project_deploy'),
    path('<int:pk>/jenkinsfile/', views.jenkinsfile_download, name='jenkinsfile_download'),
]
