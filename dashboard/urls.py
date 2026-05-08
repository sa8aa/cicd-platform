from django.urls import path, include
from . import views

urlpatterns = [
    path('',              views.home,        name='dashboard'),
    path('login/',        views.login_view,  name='login'),
    path('logout/',       views.logout_view, name='logout'),
    path('projects/',     include('projects.urls')),
    path('deployments/',  include('deployments.urls')),
]
