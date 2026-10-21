from django.urls import path
from . import views

app_name = "common"

urlpatterns = [
    path("", views.api_root, name="api-root"),
]