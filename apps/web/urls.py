from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.home, name="home"),
    path("events/", views.event_list, name="event_list"),
    path("events/<slug:slug>/", views.event_detail, name="event_detail"),
    path("events/<slug:slug>/register/", views.event_register, name="event_register"),
    path("registrations/<int:pk>/cancel/", views.registration_cancel, name="registration_cancel"),
    path("login/", views.SiteLoginView.as_view(), name="login"),
    path("register/", views.register, name="register"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("my-registrations/", views.my_registrations, name="my_registrations"),
    path("profile/", views.profile, name="profile"),
    path("profile/password/", views.SitePasswordChangeView.as_view(), name="password_change"),
]