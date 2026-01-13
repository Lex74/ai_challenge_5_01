#!/bin/bash
# Скрипт для очистки диска на удалённом Ubuntu сервере
# Использование: ssh root@project-success.ru 'bash -s' < cleanup_server.sh

set -e

echo "=== Начало очистки диска ==="
echo "Свободное место до очистки:"
df -h / | tail -1

echo ""
echo "1. Очистка apt кэша..."
apt clean
apt autoclean
apt autoremove -y

echo ""
echo "2. Очистка snap пакетов..."
# Удаление старых версий snap
snap list --all | awk '/disabled/{print $1, $3}' | while read snapname revision; do
    snap remove "$snapname" --revision="$revision" 2>/dev/null || true
done

echo ""
echo "3. Очистка systemd journal (логи)..."
journalctl --vacuum-time=3d 2>/dev/null || true
journalctl --vacuum-size=200M 2>/dev/null || true

echo ""
echo "4. Очистка старых логов в /var/log..."
find /var/log -type f -name "*.log" -mtime +7 -delete 2>/dev/null || true
find /var/log -type f -name "*.gz" -delete 2>/dev/null || true
find /var/log -type f -name "*.log.*" -mtime +30 -delete 2>/dev/null || true

echo ""
echo "5. Очистка /tmp..."
find /tmp -type f -atime +7 -delete 2>/dev/null || true
find /tmp -type d -empty -delete 2>/dev/null || true

echo ""
echo "6. Очистка Python кэша в проекте..."
cd /root/proj/ai-challenge-5-01 2>/dev/null && {
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    find . -type f -name "*.pyo" -delete 2>/dev/null || true
    echo "   Очистка кэша в проекте завершена"
} || echo "   Проект не найден, пропущено"

echo ""
echo "7. Очистка старых ядер (оставить только текущее)..."
# Удаление старых ядер, кроме текущего и одного предыдущего
OLD_KERNELS=$(dpkg -l | grep '^ii.*linux-image' | awk '{print $2}' | grep -v $(uname -r | cut -d- -f1,2) | head -n -1)
if [ ! -z "$OLD_KERNELS" ]; then
    apt-get purge -y $OLD_KERNELS 2>/dev/null || true
fi

echo ""
echo "=== Очистка завершена ==="
echo "Свободное место после очистки:"
df -h / | tail -1

echo ""
echo "Топ-10 самых больших директорий:"
du -h --max-depth=1 / 2>/dev/null | sort -hr | head -11
