import hmac

import config


def verify(password: str) -> bool:
    """Checks the admin password from config.ADMIN_PASSWORD (constant-time comparison)."""
    return hmac.compare_digest(password.encode("utf-8"), config.ADMIN_PASSWORD.encode("utf-8"))
