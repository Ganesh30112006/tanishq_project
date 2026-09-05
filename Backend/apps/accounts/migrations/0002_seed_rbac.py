"""Seed the RBAC catalog: permissions, system roles and their mapping.

Roles and permissions are administrable data, so they are seeded via a
migration rather than hard-coded lookups. Re-runnable and reversible.
"""
from __future__ import annotations

from django.db import migrations


def seed(apps, schema_editor):
    from apps.accounts.permissions import DEFAULT_ROLE_PERMISSIONS, PERMISSION_CATALOG
    from apps.common.enums import Role as RoleEnum

    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")

    for code, (category, description) in PERMISSION_CATALOG.items():
        Permission.objects.update_or_create(
            code=code, defaults={"category": category, "description": description}
        )

    label_by_code = {c: lbl for c, lbl in RoleEnum.choices}
    for role_code, perm_codes in DEFAULT_ROLE_PERMISSIONS.items():
        role, _ = Role.objects.update_or_create(
            code=role_code,
            defaults={"name": label_by_code.get(role_code, role_code), "is_system": True},
        )
        for perm_code in perm_codes:
            RolePermission.objects.get_or_create(
                role=role, permission=Permission.objects.get(code=perm_code)
            )


def unseed(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    Permission.objects.all().delete()
    Role.objects.filter(is_system=True).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
