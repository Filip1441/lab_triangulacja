import base64
import getpass
import hashlib
import hmac
import json
import os
import sys

ADMIN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "admin.json")
ITERATIONS = 200_000


def _hash(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def is_configured() -> bool:
    return os.path.exists(ADMIN_FILE)


def set_password(password: str):
    """Stores a salted PBKDF2 hash (never the password itself) in admin.json (mode 600, not tracked by git)."""
    salt = os.urandom(16)
    data = {
        "iterations": ITERATIONS,
        "salt": base64.b64encode(salt).decode(),
        "hash": base64.b64encode(_hash(password, salt, ITERATIONS)).decode(),
    }
    fd = os.open(ADMIN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)


def verify(password: str) -> bool:
    try:
        with open(ADMIN_FILE, "r") as f:
            data = json.load(f)
        expected = base64.b64decode(data["hash"])
        actual = _hash(password, base64.b64decode(data["salt"]), int(data["iterations"]))
        return hmac.compare_digest(expected, actual)
    except (OSError, ValueError, KeyError):
        return False


if __name__ == "__main__":
    # Usage: python3 -m core.admin_auth   (prompts twice, nothing is echoed or logged)
    p1 = getpass.getpass("New admin password: ")
    if not p1 or p1 != getpass.getpass("Repeat: "):
        sys.exit("Passwords empty or different - nothing changed.")
    set_password(p1)
    print(f"Admin password saved to {ADMIN_FILE}")
