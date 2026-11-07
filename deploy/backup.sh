#!/usr/bin/env bash
# Nightly copy of the database and every uploaded report, kept 14 days.
# Run by caresense-backup.timer. These copies stay on this server - copy
# /var/backups/caresense somewhere else too, or a lost disk loses the data and
# its backup together.
#
# Restore:
#   gunzip -c db-<date>.sql.gz | mysql -u <user> -p <database>
#   tar -xzf media-<date>.tar.gz -C /srv/caresense/app/Backend
set -euo pipefail

DEST=/var/backups/caresense
STAMP=$(date +%F)
umask 077

# The password goes through the environment, never the command line, where
# any user on the server could read it in the process list.
export MYSQL_PWD="$MYSQL_PASSWORD"
mysqldump -h "${MYSQL_HOST:-127.0.0.1}" -P "${MYSQL_PORT:-3306}" -u "$MYSQL_USER" \
    --single-transaction --no-tablespaces "$MYSQL_DATABASE" \
    | gzip > "$DEST/db-$STAMP.sql.gz.part"
mv "$DEST/db-$STAMP.sql.gz.part" "$DEST/db-$STAMP.sql.gz"

tar -czf "$DEST/media-$STAMP.tar.gz.part" -C /srv/caresense/app/Backend media
mv "$DEST/media-$STAMP.tar.gz.part" "$DEST/media-$STAMP.tar.gz"

find "$DEST" -type f -mtime +14 -delete
echo "Backup written: $DEST/db-$STAMP.sql.gz, $DEST/media-$STAMP.tar.gz"
