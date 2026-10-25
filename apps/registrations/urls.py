from rest_framework.routers import DefaultRouter

from .views import RegistrationViewSet

app_name = "registrations"

router = DefaultRouter()
router.register("", RegistrationViewSet, basename="registration")

urlpatterns = router.urls