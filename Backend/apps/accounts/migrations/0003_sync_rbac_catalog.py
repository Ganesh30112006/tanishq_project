"""Re-sync the RBAC catalog so permissions added after 0002 are seeded on
existing databases too. Idempotent."""
from __future__ import annotations

from django.db import migrations


def sync(apps, schema_editor):
    from apps.accounts.permissions import DEFAULT_ROLE_PERMISSIONS, PERMISSION_CATALOG
    from apps.common.enums import Role as RoleEnum

    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")

    for code, (category, description) in PERMISSION_CATALOG.items():
        Permission.objects.update_or_create(
            code=code, defaults={"category": category, "description": description}
        )
    label_by_code = dict(RoleEnum.choices)
    for role_code, perm_codes in DEFAULT_ROLE_PERMISSIONS.items():
        role, _ = Role.objects.update_or_create(
            code=role_code, defaults={"name": label_by_code.get(role_code, role_code), "is_system": True}
        )
        for perm_code in perm_codes:
            RolePermission.objects.get_or_create(
                role=role, permission=Permission.objects.get(code=perm_code)
            )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_seed_rbac")]
    operations = [migrations.RunPython(sync, migrations.RunPython.noop)]
