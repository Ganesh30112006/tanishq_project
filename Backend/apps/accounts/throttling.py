"""Login attempts counted per account, not only per client.

The ``auth`` scope limits one client address. Addresses are cheap to change,
so on its own it leaves any one account open to unlimited guessing from many
of them. This counts attempts against the email being tried, wherever they
come from.

The cost is deliberate and bounded: someone who hammers a person's email can
make that person wait until the window passes. A forced wait is a better
outcome than a guessed password.
"""
from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle


class LoginAccountThrottle(SimpleRateThrottle):
    scope = "auth_account"

    def get_cache_key(self, request, view):
        email = (request.data or {}).get("email") if hasattr(request, "data") else None
        if not isinstance(email, str) or not email.strip():
            return None  # nothing to count against; the per-client limit still applies
        return self.cache_format % {"scope": self.scope, "ident": email.strip().lower()}
