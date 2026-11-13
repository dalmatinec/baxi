#!/usr/bin/env bash
# Файл подкачки (swap), чтобы боту хватало памяти на маленьком сервере. Запускать от root:
#   bash /opt/linkhub/deploy/swap.sh        # 5 ГБ
#   bash /opt/linkhub/deploy/swap.sh 8      # другой размер в ГБ
set -euo pipefail
SIZE_GB="${1:-5}"
if swapon --show=NAME --noheadings | grep -qx /swapfile; then
    echo "Swap уже включён:"; swapon --show; free -h; exit 0
fi
if [ ! -f /swapfile ]; then
    fallocate -l "${SIZE_GB}G" /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=$((SIZE_GB * 1024)) status=progress
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
fi
swapon /swapfile
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
# swap только на крайний случай: сначала используем обычную память
echo 'vm.swappiness=10' > /etc/sysctl.d/99-linkhub-swap.conf
sysctl -q -w vm.swappiness=10
echo "Готово:"; swapon --show; free -h
