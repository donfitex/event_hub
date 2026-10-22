# apps/events/category_urls.py
from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet

app_name = "categories"

router = DefaultRouter()
router.register("", CategoryViewSet, basename="category")

urlpatterns = router.urls