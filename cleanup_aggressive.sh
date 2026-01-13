#!/bin/bash
# Агрессивная очистка диска на удалённом Ubuntu сервере
# Использование: ssh root@project-success.ru 'bash -s' < cleanup_aggressive.sh

set -e

echo "=== ДИАГНОСТИКА ПЕРЕД ОЧИСТКОЙ ==="
echo ""
echo "Свободное место:"
df -h / | tail -1
echo ""

echo "Что занимает место в /snap:"
du -sh /snap/* 2>/dev/null | sort -hr | head -10
echo ""

echo "Что занимает место в /var:"
du -sh /var/* 2>/dev/null | sort -hr | head -10
echo ""

echo "Размер journal:"
journalctl --disk-usage 2>/dev/null || echo "Не удалось проверить"
echo ""

echo "=== НАЧАЛО АГРЕССИВНОЙ ОЧИСТКИ ==="
echo ""

echo "1. Агрессивная очистка snap..."
# Удалить все отключенные версии
snap list --all | awk '/disabled/{print $1, $3}' | while read snapname revision; do
    echo "   Удаление $snapname (revision $revision)..."
    snap remove "$snapname" --revision="$revision" 2>/dev/null || true
done

# Очистить кэш snap
rm -rf /var/lib/snapd/cache/* 2>/dev/null || true

echo ""
echo "2. Агрессивная очистка systemd journal..."
# Оставить только последний день
journalctl --vacuum-time=1d 2>/dev/null || true
# Или максимум 100MB
journalctl --vacuum-size=100M 2>/dev/null || true

echo ""
echo "3. Очистка всех старых логов..."
# Удалить все .gz файлы логов
find /var/log -type f -name "*.gz" -delete 2>/dev/null || true
# Удалить логи старше 3 дней
find /var/log -type f -name "*.log" -mtime +3 -delete 2>/dev/null || true
find /var/log -type f -name "*.log.*" -mtime +3 -delete 2>/dev/null || true

echo ""
echo "4. Проверка и очистка /var/lib..."
# Проверить что там большое
echo "   Топ-10 в /var/lib:"
du -sh /var/lib/* 2>/dev/null | sort -hr | head -10

# Очистить кэш apt (если ещё есть)
rm -rf /var/lib/apt/lists/* 2>/dev/null || true
apt clean

# Очистить кэш snapd
rm -rf /var/lib/snapd/cache/* 2>/dev/null || true

# Проверить Docker (если установлен)
if command -v docker &> /dev/null; then
    echo "   Очистка Docker..."
    docker system prune -af --volumes 2>/dev/null || true
fi

echo ""
echo "5. Очистка старых ядер (более агрессивная)..."
# Удалить все старые ядра кроме текущего
CURRENT_KERNEL=$(uname -r | cut -d- -f1,2)
dpkg -l | grep '^ii.*linux-image' | awk '{print $2}' | grep -v "$CURRENT_KERNEL" | while read kernel; do
    echo "   Удаление ядра: $kernel"
    apt-get purge -y "$kernel" 2>/dev/null || true
done

# Удалить заголовки старых ядер
dpkg -l | grep '^ii.*linux-headers' | awk '{print $2}' | grep -v "$CURRENT_KERNEL" | while read headers; do
    apt-get purge -y "$headers" 2>/dev/null || true
done

apt autoremove -y

echo ""
echo "6. Очистка /usr (осторожно, только кэш)..."
# Очистить только кэш в /usr, не трогать системные файлы
find /usr -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find /usr -type f -name "*.pyc" -delete 2>/dev/null || true

echo ""
echo "7. Очистка /opt..."
# Проверить что там
du -sh /opt/* 2>/dev/null | sort -hr | head -5
# Очистить только кэш если есть
find /opt -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

echo ""
echo "8. Очистка проекта..."
cd /root/proj/ai-challenge-5-01 2>/dev/null && {
    echo "   Размер директорий проекта:"
    du -sh * 2>/dev/null | sort -hr | head -10
    
    # Очистить кэш
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    find . -type f -name "*.pyo" -delete 2>/dev/null || true
    
    # Очистить временные файлы
    find . -type f -name "*.tmp" -delete 2>/dev/null || true
    find . -type f -name "*.swp" -delete 2>/dev/null || true
    find . -type f -name ".DS_Store" -delete 2>/dev/null || true
} || echo "   Проект не найден"

echo ""
echo "9. Финальная очистка apt..."
apt clean
apt autoclean
apt autoremove -y

echo ""
echo "=== ОЧИСТКА ЗАВЕРШЕНА ==="
echo ""
echo "Свободное место после очистки:"
df -h / | tail -1
echo ""
echo "Топ-10 самых больших директорий:"
du -h --max-depth=1 / 2>/dev/null | sort -hr | head -11
echo ""
echo "Детализация /snap:"
du -sh /snap/* 2>/dev/null | sort -hr | head -5
echo ""
echo "Детализация /var:"
du -sh /var/* 2>/dev/null | sort -hr | head -5
