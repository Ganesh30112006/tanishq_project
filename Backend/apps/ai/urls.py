from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.ai.views import AiAskView, AiInteractionViewSet, AiKnowledgeViewSet

router = DefaultRouter()
router.register("interactions", AiInteractionViewSet, basename="ai-interaction")
router.register("knowledge", AiKnowledgeViewSet, basename="ai-knowledge")

urlpatterns = [
    path("ask", AiAskView.as_view(), name="ai-ask"),
    *router.urls,
]
