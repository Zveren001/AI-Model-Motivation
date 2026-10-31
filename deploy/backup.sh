#!/bin/bash
# Состояние мотиваций в Google Drive раз в сутки. Код лежит в git, клипы докачиваются из стока,
# а журнал восстановить неоткуда: без него фразы пойдут по второму кругу. В архиве .env с токенами, поэтому umask 077.
set -u

ROOT=/opt/motivation
BACKUP_DIR=/var/backups/motivation
REMOTE="gdrive:Backups/Motivation"
KEEP_LOCAL_DAYS=7
KEEP_CLOUD_DAYS=30
FILES=(post_log.json stats.json footage/used.json .env)

stamp() { date -u '+%Y-%m-%d %H:%M:%S UTC'; }

umask 077
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
ARCHIVE="$BACKUP_DIR/motivation-$(date -u +%Y-%m-%d).tar.gz"

if ! tar czf "$ARCHIVE" -C "$ROOT" "${FILES[@]}"; then
  echo "$(stamp) бэкап: не собрался архив"
  exit 1
fi
if ! rclone copy "$ARCHIVE" "$REMOTE" --no-traverse; then
  echo "$(stamp) бэкап: не загрузился в $REMOTE"
  exit 1
fi
rclone delete "$REMOTE" --min-age "${KEEP_CLOUD_DAYS}d" || echo "$(stamp) бэкап: не удалились старые архивы в облаке"
find "$BACKUP_DIR" -name 'motivation-*.tar.gz' -mtime "+$KEEP_LOCAL_DAYS" -delete
echo "$(stamp) бэкап: $(basename "$ARCHIVE") загружен, $(du -h "$ARCHIVE" | cut -f1)"
