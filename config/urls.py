from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "EventHub Administration"
admin.site.site_title = "EventHub Admin"
admin.site.index_title = "Manage events, registrations and users"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.common.urls")),
    path("api/v1/users/", include("apps.users.urls")),
    path("api/v1/events/", include("apps.events.urls")),
    path("api/v1/registrations/", include("apps.registrations.urls")),
    path("api/v1/categories/", include("apps.events.category_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)