"""DRF integration for resource-level authorization.

``ResourceAccessPermission`` runs object-level checks through the engine so a
view never has to special-case roles. Views should still scope their
``get_queryset`` with :func:`apps.authz.relationships.visible_patient_queryset`
(or an equivalent) so list endpoints authorize before returning data.
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission, SAFE_METHODS

from apps.authz.engine import Action, is_allowed

_METHOD_ACTION = {
    "GET": Action.READ,
    "HEAD": Action.READ,
    "OPTIONS": Action.READ,
    "POST": Action.CREATE,
    "PUT": Action.UPDATE,
    "PATCH": Action.UPDATE,
    "DELETE": Action.DELETE,
}


class ResourceAccessPermission(BasePermission):
    def has_permission(self, request, view) -> bool:
        # Collection-level access is gated by RBAC + queryset scoping.
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        action = getattr(view, "authz_action", None) or _METHOD_ACTION.get(request.method, Action.READ)
        if request.method in SAFE_METHODS:
            action = Action.READ
        return is_allowed(request.user, action, obj)
