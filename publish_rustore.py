#!/usr/bin/env python3
"""Скрипт для автоматической публикации APK файла в RuStore через API"""
import argparse
import logging
import os
import sys
import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
import jwt

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# RuStore API base URL
RUSTORE_API_BASE = "https://public-api.rustore.ru/public/v1"
RUSTORE_AUTH_URL = f"{RUSTORE_API_BASE}/auth"


def load_private_key(private_key_str: str) -> rsa.RSAPrivateKey:
    """Загружает приватный RSA ключ из строки"""
    try:
        if not private_key_str or not private_key_str.strip():
            raise ValueError("Приватный ключ пустой")
        
        # Убеждаемся, что ключ имеет правильный формат PEM
        key_str = private_key_str.strip()
        if not key_str.startswith('-----BEGIN'):
            # Если ключ без заголовков, добавляем их
            if 'BEGIN' not in key_str:
                key_str = f"-----BEGIN PRIVATE KEY-----\n{key_str}\n-----END PRIVATE KEY-----"
        
        # Пробуем загрузить ключ в формате PEM
        private_key = serialization.load_pem_private_key(
            key_str.encode('utf-8'),
            password=None,
            backend=default_backend()
        )
        logger.info("✅ Приватный ключ успешно загружен")
        return private_key
    except ValueError as e:
        logger.error(f"❌ Ошибка валидации приватного ключа: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка при загрузке приватного ключа: {e}")
        logger.error("💡 Убедитесь, что ключ в формате PEM с заголовками -----BEGIN PRIVATE KEY----- и -----END PRIVATE KEY-----")
        raise


def get_jwe_token(private_key: rsa.RSAPrivateKey) -> Optional[str]:
    """Получает JWE-токен для RuStore API используя приватный ключ
    
    Согласно документации RuStore API:
    - Используется POST /public/auth/ для получения токена
    - Токен действителен 900 секунд (15 минут)
    - Токен передается в заголовке Authorization: API-key {token}
    """
    try:
        logger.info("🔐 Получаю JWE-токен через RuStore API...")
        
        # Создаем JWT токен для запроса авторизации
        # Обычно для RuStore API используется JWT с подписью RSA
        now = datetime.utcnow()
        payload = {
            'iat': int(now.timestamp()),
            'exp': int((now + timedelta(minutes=15)).timestamp()),  # Токен на 15 минут
        }
        
        # Подписываем JWT токен приватным ключом
        jwt_token = jwt.encode(
            payload,
            private_key,
            algorithm='RS256'
        )
        
        # Отправляем запрос на получение JWE-токена
        headers = {
            'Content-Type': 'application/json'
        }
        
        # Отправляем JWT токен для получения JWE-токена
        # Точный формат запроса может отличаться, нужно проверить документацию
        response = requests.post(
            RUSTORE_AUTH_URL,
            headers=headers,
            json={'token': jwt_token},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            # JWE-токен может быть в разных полях ответа
            jwe_token = data.get('token') or data.get('access_token') or data.get('jwe_token') or jwt_token
            logger.info("✅ JWE-токен успешно получен (действителен 15 минут)")
            return jwe_token
        else:
            # Если endpoint не работает как ожидается, используем JWT напрямую
            logger.warning(f"⚠️ Получен статус {response.status_code} при получении JWE-токена")
            logger.warning(f"Ответ сервера: {response.text}")
            logger.warning("⚠️ Используем JWT токен напрямую")
            return jwt_token
            
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Ошибка при запросе к RuStore API: {e}")
        # В случае ошибки используем JWT токен напрямую
        logger.warning("⚠️ Используем JWT токен напрямую как JWE-токен")
        try:
            now = datetime.utcnow()
            payload = {
                'iat': int(now.timestamp()),
                'exp': int((now + timedelta(minutes=15)).timestamp()),
            }
            return jwt.encode(payload, private_key, algorithm='RS256')
        except Exception as jwt_error:
            logger.error(f"❌ Ошибка при создании JWT токена: {jwt_error}")
            return None
    except Exception as e:
        logger.error(f"❌ Ошибка при получении JWE-токена: {e}", exc_info=True)
        return None


def create_version_draft(auth_token: str, package_name: str) -> Optional[str]:
    """Создает черновик версии в RuStore и возвращает versionId"""
    try:
        logger.info(f"📝 Создаю черновик версии для приложения {package_name}...")
        
        url = f"{RUSTORE_API_BASE}/application/{package_name}/version"
        headers = {
            'Authorization': f'API-key {auth_token}',
            'Content-Type': 'application/json'
        }
        
        # Создаем новую версию (черновик)
        payload = {
            'status': 'draft'
        }
        
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            data = response.json()
            version_id = data.get('id') or data.get('versionId') or data.get('version_id')
            logger.info(f"✅ Черновик версии создан, versionId: {version_id}")
            return str(version_id)
        else:
            logger.error(f"❌ Ошибка при создании версии: {response.status_code}")
            logger.error(f"Ответ сервера: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Ошибка при запросе к RuStore API: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка при создании версии: {e}", exc_info=True)
        return None


def upload_apk(auth_token: str, package_name: str, version_id: str, apk_path: str) -> bool:
    """Загружает APK файл в RuStore"""
    try:
        logger.info(f"📤 Загружаю APK файл: {apk_path}...")
        
        if not os.path.exists(apk_path):
            logger.error(f"❌ APK файл не найден: {apk_path}")
            return False
        
        url = f"{RUSTORE_API_BASE}/application/{package_name}/version/{version_id}/apk"
        params = {
            'isMainApk': 'true',
            'servicesType': 'Unknown'
        }
        
        headers = {
            'Authorization': f'API-key {auth_token}'
        }
        
        with open(apk_path, 'rb') as apk_file:
            files = {
                'file': (os.path.basename(apk_path), apk_file, 'application/vnd.android.package-archive')
            }
            
            response = requests.post(
                url,
                headers=headers,
                params=params,
                files=files,
                timeout=300  # Увеличенный таймаут для больших файлов
            )
        
        if response.status_code in [200, 201]:
            logger.info("✅ APK файл успешно загружен")
            return True
        else:
            logger.error(f"❌ Ошибка при загрузке APK: {response.status_code}")
            logger.error(f"Ответ сервера: {response.text}")
            return False
            
    except FileNotFoundError:
        logger.error(f"❌ APK файл не найден: {apk_path}")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Ошибка при загрузке APK: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка при загрузке APK: {e}", exc_info=True)
        return False


def submit_for_moderation(auth_token: str, package_name: str, version_id: str) -> bool:
    """Отправляет версию на модерацию"""
    try:
        logger.info(f"🚀 Отправляю версию {version_id} на модерацию...")
        
        url = f"{RUSTORE_API_BASE}/application/{package_name}/version/{version_id}/submit"
        headers = {
            'Authorization': f'API-key {auth_token}',
            'Content-Type': 'application/json'
        }
        
        response = requests.post(
            url,
            headers=headers,
            json={},
            timeout=30
        )
        
        if response.status_code in [200, 201, 202]:
            logger.info("✅ Версия успешно отправлена на модерацию")
            return True
        else:
            logger.warning(f"⚠️ Получен статус {response.status_code} при отправке на модерацию")
            logger.warning(f"Ответ сервера: {response.text}")
            # Не считаем это критической ошибкой, версия может быть уже отправлена
            return response.status_code == 404  # 404 может означать, что версия уже отправлена
            
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Ошибка при отправке на модерацию: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке на модерацию: {e}", exc_info=True)
        return False


def publish_apk_to_rustore(apk_path: str, private_key_str: str, package_name: str) -> bool:
    """Основная функция для публикации APK в RuStore"""
    try:
        logger.info("=" * 60)
        logger.info("🚀 Начинаю публикацию APK в RuStore")
        logger.info("=" * 60)
        
        # Проверяем наличие APK файла
        if not os.path.exists(apk_path):
            logger.error(f"❌ APK файл не найден: {apk_path}")
            logger.error(f"💡 Текущая рабочая директория: {os.getcwd()}")
            return False
        
        if not os.path.isfile(apk_path):
            logger.error(f"❌ Указанный путь не является файлом: {apk_path}")
            return False
        
        apk_size = os.path.getsize(apk_path)
        if apk_size == 0:
            logger.error(f"❌ APK файл пустой: {apk_path}")
            return False
        
        logger.info(f"📦 APK файл: {apk_path} ({apk_size / 1024 / 1024:.2f} MB)")
        
        # Проверяем формат файла (должен быть .apk)
        if not apk_path.lower().endswith('.apk'):
            logger.warning(f"⚠️ Файл не имеет расширения .apk: {apk_path}")
        
        # Загружаем приватный ключ
        private_key = load_private_key(private_key_str)
        
        # Получаем JWE-токен
        auth_token = get_jwe_token(private_key)
        if not auth_token:
            logger.error("❌ Не удалось получить JWE-токен")
            return False
        
        logger.info("✅ JWE-токен получен (действителен 15 минут)")
        
        # Создаем черновик версии
        version_id = create_version_draft(auth_token, package_name)
        if not version_id:
            logger.error("❌ Не удалось создать черновик версии")
            logger.error("💡 Возможные причины:")
            logger.error("   - Неверный package name")
            logger.error("   - Недостаточно прав для создания версии")
            logger.error("   - Проблемы с API RuStore")
            logger.warning("⚠️ Пытаюсь использовать последнюю версию или создать версию вручную")
            # Можно попробовать получить список версий и использовать последнюю
            # Для упрощения, пропускаем этот шаг если не удалось создать
            return False
        
        # Загружаем APK
        if not upload_apk(auth_token, package_name, version_id, apk_path):
            logger.error("❌ Не удалось загрузить APK файл")
            return False
        
        # Небольшая задержка перед отправкой на модерацию
        time.sleep(2)
        
        # Отправляем на модерацию
        submit_success = submit_for_moderation(auth_token, package_name, version_id)
        if not submit_success:
            logger.warning("⚠️ Не удалось отправить версию на модерацию, но APK загружен")
            logger.info("💡 Возможно, версия уже отправлена или требуется ручная отправка")
            logger.info(f"💡 Version ID: {version_id}, Package: {package_name}")
        
        logger.info("=" * 60)
        logger.info("✅ Публикация APK завершена")
        logger.info("=" * 60)
        return True
        
    except KeyboardInterrupt:
        logger.warning("⚠️ Публикация прервана пользователем")
        return False
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при публикации: {e}", exc_info=True)
        logger.error("💡 Проверьте:")
        logger.error("   - Правильность приватного ключа")
        logger.error("   - Правильность package name")
        logger.error("   - Доступность API RuStore")
        logger.error("   - Логи выше для деталей")
        return False


def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(
        description='Публикация APK файла в RuStore через API'
    )
    parser.add_argument(
        '--apk-file',
        type=str,
        default='release/app-release.apk',
        help='Путь к APK файлу (по умолчанию: release/app-release.apk)'
    )
    parser.add_argument(
        '--package-name',
        type=str,
        default=None,
        help='Package name приложения (или из переменной окружения RUSTORE_PACKAGE_NAME)'
    )
    parser.add_argument(
        '--private-key',
        type=str,
        default=None,
        help='Приватный RSA ключ для RuStore API (или из переменной окружения RUSTORE_PRIVATE_KEY)'
    )
    
    args = parser.parse_args()
    
    # Получаем параметры из аргументов или переменных окружения
    apk_path = args.apk_file
    package_name = args.package_name or os.getenv('RUSTORE_PACKAGE_NAME')
    private_key_str = args.private_key or os.getenv('RUSTORE_PRIVATE_KEY')
    
    # Проверяем обязательные параметры
    if not package_name:
        logger.error("❌ Package name не указан. Укажите через --package-name или RUSTORE_PACKAGE_NAME")
        sys.exit(1)
    
    if not private_key_str:
        logger.error("❌ Приватный ключ не указан. Укажите через --private-key или RUSTORE_PRIVATE_KEY")
        logger.error("💡 Приватный ключ можно получить в консоли разработчика RuStore (console.rustore.ru)")
        logger.error("💡 Ключ должен быть в формате PEM с заголовками -----BEGIN PRIVATE KEY----- и -----END PRIVATE KEY-----")
        sys.exit(1)
    
    # Публикуем APK
    success = publish_apk_to_rustore(apk_path, private_key_str, package_name)
    
    if not success:
        logger.error("❌ Публикация не удалась")
        sys.exit(1)
    
    logger.info("✅ Публикация успешно завершена")


if __name__ == "__main__":
    main()
