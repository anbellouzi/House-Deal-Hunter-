from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.auctions.api import AlertViewSet, AuctionViewSet
from apps.dashboard import views as dash

router = DefaultRouter()
router.register(r"auctions", AuctionViewSet, basename="auction")
router.register(r"alerts", AlertViewSet, basename="alert")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("api-auth/", include("rest_framework.urls")),

    # Dashboard
    path("", dash.dashboard_home, name="dashboard"),
    path("auction/<int:pk>/", dash.auction_detail, name="auction-detail"),
]
