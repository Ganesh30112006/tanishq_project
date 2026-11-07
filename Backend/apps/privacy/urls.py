from __future__ import annotations

from django.urls import path

from apps.privacy.views import (
    ConsentDocumentsView,
    ErasureAdminView,
    MyConsentView,
    MyErasureView,
)

urlpatterns = [
    path("consent", MyConsentView.as_view(), name="privacy-consent"),
    path("consent/documents", ConsentDocumentsView.as_view(), name="privacy-consent-documents"),
    path("erasure", MyErasureView.as_view(), name="privacy-erasure"),
    path("erasure/requests", ErasureAdminView.as_view(), name="privacy-erasure-admin"),
    path(
        "erasure/requests/<uuid:public_id>",
        ErasureAdminView.as_view(),
        name="privacy-erasure-decide",
    ),
]
