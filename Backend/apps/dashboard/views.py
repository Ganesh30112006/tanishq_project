"""Role-aware dashboard summary (spec sections 2, 42).

The role shown is always the caller's own real role - see
``apps.dashboard.service.effective_role``. An optional ``role`` query param
may only select among the roles the caller actually holds; any other value
is silently ignored rather than changing authorization (spec section 54).
"""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dashboard.serializers import DashboardSummarySerializer
from apps.dashboard.service import DashboardService


class DashboardSummaryView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DashboardSummarySerializer

    def get(self, request: Request) -> Response:
        requested_role = request.query_params.get("role")
        summary = DashboardService().summary(request.user, requested_role=requested_role)
        return Response(DashboardSummarySerializer(summary).data)
