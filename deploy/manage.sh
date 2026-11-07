#!/usr/bin/env bash
# Run a Django management command on the server, as the app user, with the
# production settings loaded:
#
#   sudo bash /srv/caresense/app/deploy/manage.sh check_privacy
set -euo pipefail

ENV_FILE=/etc/caresense/caresense.env
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo." >&2; exit 1; }

# Read the settings line by line rather than `source` them: values such as
# "CareSense <no-reply@...>" are fine in the file and invalid shell.
while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in '' | '#'*) continue ;; esac
    export "$line"
done < "$ENV_FILE"

cd /srv/caresense/app/Backend
exec runuser -u caresense -- /srv/caresense/venv/bin/python manage.py "$@"
