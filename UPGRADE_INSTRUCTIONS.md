# Инструкция по обновлению зависимостей

## Проблема

Ошибка при запуске бота:
```
TypeError: AsyncClient.__init__() got an unexpected keyword argument 'proxies'
```

Эта ошибка возникает из-за конфликта версий:
- `python-telegram-bot==20.7` использует старый API `httpx` (с параметром `proxies`)
- `mcp>=0.9.0` требует новую версию `httpx` (без параметра `proxies`)

## Решение

Обновите `python-telegram-bot` до версии 21.x или выше, которая поддерживает новую версию `httpx`.

### На сервере выполните:

```bash
# Перейдите в директорию проекта
cd /root/proj/ai-challenge-5-01

# Обновите зависимости
pip3 install --upgrade python-telegram-bot>=21.0

# Или переустановите все зависимости
pip3 install -r requirements.txt --upgrade
```

### После обновления перезапустите сервис:

```bash
sudo systemctl restart ai-challenge.service
```

### Проверьте статус:

```bash
sudo systemctl status ai-challenge.service
```

## Примечание

Если вы используете виртуальное окружение, активируйте его перед обновлением:

```bash
source venv/bin/activate
pip install --upgrade python-telegram-bot>=21.0
deactivate
```

## Изменения в requirements.txt

Файл `requirements.txt` обновлен:
- `python-telegram-bot==20.7` → `python-telegram-bot>=21.0`

Это обеспечит совместимость с новой версией `httpx`, требуемой для `mcp`.

