#!/bin/bash
# Sets the password for the app's admin button (run on the Pi, as pi_admin). The password is asked
# interactively and only a salted hash is stored in admin.json (not tracked by git).
cd "$(dirname "$0")/.."
python3 -m core.admin_auth
