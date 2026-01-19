#!/usr/bin/env python3
"""Скрипт для автоматической публикации APK файла в RuStore через API"""
import argparse
import logging
import os
import sys
import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import base64
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# RuStore API base URL
RUSTORE_API_BASE = "https://public-api.rustore.ru/public/v1"
# URL авторизации без версии, согласно документации RuStore
RUSTORE_AUTH_URL = "https://public-api.rustore.ru/public/auth"


def load_private_key(private_key_str: str) -> rsa.RSAPrivateKey:
    """Загружает приватный RSA ключ из строки (поддерживает PEM и base64 форматы)"""
    try:
        if not private_key_str or not private_key_str.strip():
            raise ValueError("Приватный ключ пустой")
        
        key_str = private_key_str.strip()
        
        # Проверяем, является ли ключ base64 (начинается с MII... и не содержит BEGIN)
        if not key_str.startswith('-----BEGIN') and 'BEGIN' not in key_str:
            # Пробуем загрузить как base64 (как в примере RuStore)
            try:
                key_bytes = base64.b64decode(key_str)
                private_key = serialization.load_der_private_key(
                    key_bytes,
                    password=None,
                    backend=default_backend()
                )
                logger.info("✅ Приватный ключ успешно загружен (base64 формат)")
                return private_key
            except Exception as base64_error:
                logger.debug(f"Не удалось загрузить как base64: {base64_error}")
                # Пробуем добавить PEM заголовки
                key_str = f"-----BEGIN PRIVATE KEY-----\n{key_str}\n-----END PRIVATE KEY-----"
        
        # Пробуем загрузить ключ в формате PEM
        private_key = serialization.load_pem_private_key(
            key_str.encode('utf-8'),
            password=None,
            backend=default_backend()
        )
        logger.info("✅ Приватный ключ успешно загружен (PEM формат)")
        return private_key
    except ValueError as e:
        logger.error(f"❌ Ошибка валидации приватного ключа: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка при загрузке приватного ключа: {e}")
        logger.error("💡 Убедитесь, что ключ в формате PEM или base64")
        raise


def create_signature(private_key: rsa.RSAPrivateKey, key_id: str, timestamp: str) -> str:
    """Создает RSA-подпись SHA-512 от конкатенации keyId + timestamp
    
    Согласно документации RuStore API:
    - Сообщение: конкатенация keyId + timestamp (без разделителей)
    - Алгоритм: SHA512withRSA (PKCS#1 v1.5)
    - Результат кодируется в Base64
    
    Args:
        private_key: Приватный RSA ключ
        key_id: ID ключа
        timestamp: Временная метка в формате ISO 8601
        
    Returns:
        Base64-кодированная подпись
    """
    # Конкатенируем keyId + timestamp (без разделителей, согласно документации)
    message = f"{key_id}{timestamp}".encode('utf-8')
    
    # Подписываем приватным ключом с алгоритмом SHA512withRSA
    # Метод sign() автоматически вычисляет SHA-512 хеш и подписывает его
    signature = private_key.sign(
        message,
        padding.PKCS1v15(),
        hashes.SHA512()
    )
    
    # Кодируем в Base64
    return base64.b64encode(signature).decode('utf-8')


def get_jwe_token(private_key: rsa.RSAPrivateKey, key_id: str, max_retries: int = 3) -> Optional[str]:
    """Получает JWE-токен для RuStore API используя приватный ключ
    
    Согласно документации RuStore API:
    - Используется POST /public/auth/ для получения токена
    - Отправляются keyId, timestamp и signature (RSA-подпись SHA-512)
    - Токен действителен 900 секунд (15 минут)
    - Токен передается в заголовке Public-Token: {token}
    
    Args:
        private_key: Приватный RSA ключ для создания подписи
        key_id: ID ключа из консоли RuStore
        max_retries: Максимальное количество попыток при временных ошибках сервера
        
    Returns:
        JWE-токен или None в случае ошибки
    """
    # Проверка наличия приватного ключа
    if private_key is None:
        logger.error("❌ Приватный ключ не передан (None)")
        return None
    
    if not key_id or not key_id.strip():
        logger.error("❌ Key ID не указан")
        logger.error("💡 Укажите RUSTORE_KEY_ID в секретах GitHub")
        return None
    
    # Отправляем запрос на получение JWE-токена с retry логикой
    headers = {
        'Content-Type': 'application/json'
    }
    
    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                # Экспоненциальная задержка между попытками
                delay = min(2 ** (attempt - 1), 10)  # Максимум 10 секунд
                logger.info(f"🔄 Повторная попытка {attempt}/{max_retries} через {delay} секунд...")
                time.sleep(delay)
            else:
                logger.info("🔐 Получаю JWE-токен через RuStore API...")
            
            # Создаем timestamp в формате ISO 8601 с микросекундами (как в примере RuStore)
            # Пример из документации: 2022-07-08T13:24:41.8328711+03:00
            now = datetime.now(timezone.utc)
            timestamp = now.isoformat(timespec='microseconds')
            
            # Создаем подпись
            try:
                signature = create_signature(private_key, key_id, timestamp)
            except Exception as sig_error:
                logger.error(f"❌ Ошибка при создании подписи: {sig_error}")
                return None
            
            # Формируем тело запроса
            payload = {
                'keyId': key_id,
                'timestamp': timestamp,
                'signature': signature
            }
            
            # Отправляем запрос
            response = requests.post(
                RUSTORE_AUTH_URL,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            # Безопасная обработка ответа
            if response.status_code == 200:
                try:
                    data = response.json()
                    
                    # Проверяем код ответа согласно документации RuStore
                    response_code = data.get('code')
                    if response_code != 'OK':
                        error_message = data.get('message') or 'Неизвестная ошибка'
                        logger.error(f"❌ API вернул ошибку: {error_message}")
                        return None
                    
                    # JWE-токен находится в body.jwe согласно документации RuStore
                    body = data.get('body', {})
                    jwe_token = body.get('jwe') if isinstance(body, dict) else None
                    
                    # Fallback для обратной совместимости
                    if not jwe_token:
                        jwe_token = data.get('jwe') or data.get('token') or data.get('access_token')
                    
                    if jwe_token:
                        ttl = body.get('ttl', 900) if isinstance(body, dict) else 900
                        logger.info(f"✅ JWE-токен успешно получен (действителен {ttl} секунд)")
                        return jwe_token
                    else:
                        logger.error("❌ JWE-токен не найден в ответе API")
                        logger.error(f"💡 Поля в ответе: {list(data.keys()) if isinstance(data, dict) else 'не JSON'}")
                        return None
                except ValueError as json_error:
                    logger.error(f"❌ Ошибка при парсинге JSON ответа: {json_error}")
                    logger.error(f"💡 Ответ сервера: {response.text[:200]}...")
                    return None
            elif response.status_code == 401:
                logger.error("❌ Ошибка авторизации: неверный приватный ключ, keyId или подпись")
                logger.error("💡 Проверьте правильность приватного ключа и keyId в секретах GitHub")
                # Не повторяем при 401 - это ошибка конфигурации
                return None
            elif response.status_code == 403:
                logger.error("❌ Доступ запрещен: недостаточно прав для получения токена")
                logger.error("💡 Проверьте настройки ключа в консоли RuStore")
                return None
            elif response.status_code == 400:
                logger.error("❌ Неверный запрос при получении токена")
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message') or error_data.get('error') or 'Неизвестная ошибка'
                    logger.error(f"💡 Детали: {error_msg}")
                except:
                    logger.error(f"💡 Ответ сервера: {response.text[:200]}...")
                return None
            elif response.status_code in [502, 503, 504]:
                # Временные ошибки сервера - повторяем запрос
                logger.debug(f"Ответ сервера ({response.status_code}): {response.text[:500]}")
                if attempt < max_retries:
                    logger.warning(f"⚠️ Временная ошибка сервера {response.status_code}, повторяю попытку...")
                    continue
                else:
                    logger.error(f"❌ Ошибка сервера RuStore API после {max_retries} попыток: {response.status_code}")
                    logger.error(f"💡 Ответ сервера: {response.text[:500]}")
                    return None
            elif response.status_code >= 500:
                # Другие ошибки сервера
                logger.error(f"❌ Ошибка сервера RuStore API: {response.status_code}")
                if attempt < max_retries:
                    logger.warning(f"⚠️ Повторяю попытку {attempt + 1}/{max_retries}...")
                    continue
                else:
                    return None
            else:
                # Для других статусов логируем только статус
                logger.error(f"❌ Неожиданный статус ответа: {response.status_code}")
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message') or error_data.get('error') or 'Неизвестная ошибка'
                    logger.error(f"💡 Детали: {error_msg}")
                except:
                    pass
                return None
                
        except requests.exceptions.Timeout:
            if attempt < max_retries:
                logger.warning(f"⚠️ Таймаут при запросе к RuStore API, повторяю попытку {attempt + 1}/{max_retries}...")
                continue
            else:
                logger.error("❌ Таймаут при запросе к RuStore API после всех попыток")
                logger.error("💡 Проверьте доступность API RuStore")
                return None
        except requests.exceptions.ConnectionError as e:
            if attempt < max_retries:
                logger.warning(f"⚠️ Ошибка подключения к RuStore API, повторяю попытку {attempt + 1}/{max_retries}...")
                continue
            else:
                logger.error(f"❌ Ошибка подключения к RuStore API после всех попыток: {type(e).__name__}")
                logger.error("💡 Проверьте доступность API RuStore и интернет-соединение")
                return None
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                logger.warning(f"⚠️ Ошибка при запросе к RuStore API ({type(e).__name__}), повторяю попытку {attempt + 1}/{max_retries}...")
                continue
            else:
                logger.error(f"❌ Ошибка при запросе к RuStore API после всех попыток: {type(e).__name__}")
                return None
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при получении JWE-токена: {type(e).__name__}")
            logger.debug(f"Детали ошибки: {e}", exc_info=True)
            return None
    
    # Если дошли сюда, значит все попытки исчерпаны
    logger.error(f"❌ Не удалось получить JWE-токен после {max_retries} попыток")
    return None


def create_version_draft(auth_token: str, package_name: str) -> Optional[str]:
    """Создает черновик версии в RuStore и возвращает versionId
    
    Args:
        auth_token: JWE-токен для авторизации
        package_name: Package name приложения
        
    Returns:
        versionId созданной версии или None в случае ошибки
    """
    # Проверка входных параметров
    if not auth_token or not auth_token.strip():
        logger.error("❌ Токен авторизации не указан или пустой")
        return None
    
    if not package_name or not package_name.strip():
        logger.error("❌ Package name не указан или пустой")
        return None
    
    try:
        logger.info(f"📝 Создаю черновик версии для приложения {package_name}...")
        
        url = f"{RUSTORE_API_BASE}/application/{package_name}/version"
        headers = {
            'Public-Token': auth_token,
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
            try:
                data = response.json()
                version_id = data.get('id') or data.get('versionId') or data.get('version_id')
                if version_id:
                    logger.info(f"✅ Черновик версии создан, versionId: {version_id}")
                    return str(version_id)
                else:
                    logger.error("❌ versionId не найден в ответе API")
                    logger.debug(f"Ответ API: {data}")
                    return None
            except ValueError as json_error:
                logger.error(f"❌ Ошибка при парсинге JSON ответа: {json_error}")
                return None
        elif response.status_code == 401:
            logger.error("❌ Ошибка авторизации: неверный токен или токен истек")
            logger.error(f"💡 Ответ сервера: {response.text[:500]}")
            return None
        elif response.status_code == 403:
            logger.error("❌ Доступ запрещен: недостаточно прав для создания версии")
            logger.error("💡 Проверьте настройки ключа в консоли RuStore")
            return None
        elif response.status_code == 404:
            logger.error(f"❌ Приложение не найдено: {package_name}")
            logger.error("💡 Проверьте правильность package name")
            return None
        elif response.status_code == 400:
            # Проверяем, есть ли уже черновик версии
            try:
                error_data = response.json()
                error_message = error_data.get('message', '')
                
                # Если уже есть черновик, извлекаем его ID
                if 'already have draft version with ID' in error_message:
                    import re
                    match = re.search(r'ID\s*=\s*(\d+)', error_message)
                    if match:
                        existing_version_id = match.group(1)
                        logger.info(f"📝 Найден существующий черновик версии: {existing_version_id}")
                        return existing_version_id
                
                logger.error("❌ Неверный запрос при создании версии")
                logger.error(f"💡 Ответ сервера: {error_message}")
            except:
                logger.error("❌ Неверный запрос при создании версии")
                logger.error(f"💡 Ответ сервера: {response.text[:500]}")
            return None
        elif response.status_code >= 500:
            logger.error(f"❌ Ошибка сервера RuStore API: {response.status_code}")
            return None
        else:
            logger.error(f"❌ Ошибка при создании версии: {response.status_code}")
            # Не логируем полный ответ для безопасности
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Ошибка при запросе к RuStore API: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка при создании версии: {e}", exc_info=True)
        return None


def upload_apk(auth_token: str, package_name: str, version_id: str, apk_path: str) -> bool:
    """Загружает APK файл в RuStore
    
    Args:
        auth_token: JWE-токен для авторизации
        package_name: Package name приложения
        version_id: ID версии для загрузки APK
        apk_path: Путь к APK файлу
        
    Returns:
        True если загрузка успешна, False в противном случае
    """
    # Проверка наличия файла перед загрузкой
    if not apk_path or not apk_path.strip():
        logger.error("❌ Путь к APK файлу не указан")
        return False
    
    if not os.path.exists(apk_path):
        logger.error(f"❌ APK файл не найден: {apk_path}")
        logger.error(f"💡 Текущая рабочая директория: {os.getcwd()}")
        return False
    
    if not os.path.isfile(apk_path):
        logger.error(f"❌ Указанный путь не является файлом: {apk_path}")
        return False
    
    # Проверка размера файла
    try:
        apk_size = os.path.getsize(apk_path)
        if apk_size == 0:
            logger.error(f"❌ APK файл пустой: {apk_path}")
            return False
        # Максимальный размер APK в RuStore: 5GB
        max_size = 5 * 1024 * 1024 * 1024  # 5GB в байтах
        if apk_size > max_size:
            logger.error(f"❌ APK файл слишком большой: {apk_size / 1024 / 1024 / 1024:.2f} GB")
            logger.error(f"💡 Максимальный размер: 5 GB")
            return False
    except OSError as e:
        logger.error(f"❌ Ошибка при проверке размера файла: {e}")
        return False
    
    try:
        logger.info(f"📤 Загружаю APK файл: {apk_path} ({os.path.getsize(apk_path) / 1024 / 1024:.2f} MB)...")
        
        url = f"{RUSTORE_API_BASE}/application/{package_name}/version/{version_id}/apk"
        params = {
            'isMainApk': 'true',
            'servicesType': 'Unknown'
        }
        
        headers = {
            'Public-Token': auth_token
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
        elif response.status_code == 401:
            logger.error("❌ Ошибка авторизации: неверный токен или токен истек")
            logger.error("💡 Проверьте правильность приватного ключа")
            return False
        elif response.status_code == 403:
            logger.error("❌ Доступ запрещен: недостаточно прав для загрузки APK")
            logger.error("💡 Проверьте настройки ключа в консоли RuStore")
            return False
        elif response.status_code == 404:
            logger.error(f"❌ Версия или приложение не найдено")
            logger.error(f"💡 Version ID: {version_id}, Package: {package_name}")
            return False
        elif response.status_code == 400:
            # Проверяем, не загружен ли APK уже
            try:
                error_data = response.json()
                error_message = error_data.get('message', '')
                
                if 'already uploaded' in error_message.lower():
                    logger.info("✅ APK файл уже загружен в эту версию")
                    return True
                
                logger.error("❌ Неверный запрос при загрузке APK")
                logger.error(f"💡 Ответ сервера: {error_message}")
            except:
                logger.error("❌ Неверный запрос при загрузке APK")
                logger.error(f"💡 Ответ сервера: {response.text[:500]}")
            return False
        elif response.status_code == 413:
            logger.error("❌ APK файл слишком большой")
            logger.error("💡 Максимальный размер APK: 5GB")
            return False
        elif response.status_code >= 500:
            logger.error(f"❌ Ошибка сервера RuStore API: {response.status_code}")
            logger.error("💡 Попробуйте повторить запрос позже")
            return False
        else:
            logger.error(f"❌ Ошибка при загрузке APK: {response.status_code}")
            # Не логируем полный ответ для безопасности
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
    """Отправляет версию на модерацию
    
    Args:
        auth_token: JWE-токен для авторизации
        package_name: Package name приложения
        version_id: ID версии для отправки на модерацию
        
    Returns:
        True если отправка успешна, False в противном случае
    """
    # Проверка входных параметров
    if not auth_token or not auth_token.strip():
        logger.error("❌ Токен авторизации не указан или пустой")
        return False
    
    if not package_name or not package_name.strip():
        logger.error("❌ Package name не указан или пустой")
        return False
    
    if not version_id or not version_id.strip():
        logger.error("❌ Version ID не указан или пустой")
        return False
    
    try:
        logger.info(f"🚀 Отправляю версию {version_id} на модерацию...")
        
        url = f"{RUSTORE_API_BASE}/application/{package_name}/version/{version_id}/submit"
        headers = {
            'Public-Token': auth_token,
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
        elif response.status_code == 401:
            logger.error("❌ Ошибка авторизации: неверный токен или токен истек")
            logger.error("💡 Проверьте правильность приватного ключа")
            return False
        elif response.status_code == 403:
            logger.error("❌ Доступ запрещен: недостаточно прав для отправки на модерацию")
            logger.error("💡 Проверьте настройки ключа в консоли RuStore")
            return False
        elif response.status_code == 404:
            # 404 может означать, что версия уже отправлена или не существует
            logger.warning("⚠️ Версия не найдена или уже отправлена на модерацию")
            return True  # Не считаем это критической ошибкой
        elif response.status_code == 400:
            logger.warning("⚠️ Неверный запрос при отправке на модерацию")
            logger.warning("💡 Возможно, версия уже отправлена или требуется дополнительная информация")
            return False
        elif response.status_code >= 500:
            logger.error(f"❌ Ошибка сервера RuStore API: {response.status_code}")
            return False
        else:
            logger.warning(f"⚠️ Получен статус {response.status_code} при отправке на модерацию")
            # Не логируем полный ответ для безопасности
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Ошибка при отправке на модерацию: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке на модерацию: {e}", exc_info=True)
        return False


def publish_apk_to_rustore(apk_path: str, private_key_str: str, package_name: str, key_id: Optional[str] = None) -> bool:
    """Основная функция для публикации APK в RuStore
    
    Args:
        apk_path: Путь к APK файлу
        private_key_str: Приватный RSA ключ в формате строки
        package_name: Package name приложения
        
    Returns:
        True если публикация успешна, False в противном случае
    """
    # Проверка обязательных параметров
    if not private_key_str or not private_key_str.strip():
        logger.error("❌ Приватный ключ не указан или пустой")
        return False
    
    if not package_name or not package_name.strip():
        logger.error("❌ Package name не указан или пустой")
        return False
    
    if not apk_path or not apk_path.strip():
        logger.error("❌ Путь к APK файлу не указан или пустой")
        return False
    
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
        auth_token = get_jwe_token(private_key, key_id)
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
        
        logger.info(f"💡 Version ID: {version_id}, Package: {package_name}")
        logger.info("=" * 60)
        logger.info("✅ APK успешно загружен в RuStore")
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
    parser.add_argument(
        '--key-id',
        type=str,
        default=None,
        help='ID ключа API RuStore (или из переменной окружения RUSTORE_KEY_ID)'
    )
    
    args = parser.parse_args()
    
    # Получаем параметры из аргументов или переменных окружения
    apk_path = args.apk_file
    package_name = args.package_name or os.getenv('RUSTORE_PACKAGE_NAME')
    private_key_str = args.private_key or os.getenv('RUSTORE_PRIVATE_KEY')
    key_id = args.key_id or os.getenv('RUSTORE_KEY_ID')
    
    # Проверяем обязательные параметры с детальными сообщениями
    missing_params = []
    
    if not package_name:
        missing_params.append("RUSTORE_PACKAGE_NAME")
        logger.error("❌ Package name не указан")
        logger.error("💡 Укажите через --package-name или установите переменную окружения RUSTORE_PACKAGE_NAME")
        logger.error("💡 Пример: export RUSTORE_PACKAGE_NAME=com.example.myapp")
    
    if not private_key_str:
        missing_params.append("RUSTORE_PRIVATE_KEY")
        logger.error("❌ Приватный ключ не указан")
        logger.error("💡 Укажите через --private-key или установите переменную окружения RUSTORE_PRIVATE_KEY")
        logger.error("💡 Приватный ключ можно получить в консоли разработчика RuStore (console.rustore.ru)")
        logger.error("💡 Ключ должен быть в формате PEM с заголовками:")
        logger.error("   -----BEGIN PRIVATE KEY-----")
        logger.error("   ...")
        logger.error("   -----END PRIVATE KEY-----")
    
    if not key_id:
        missing_params.append("RUSTORE_KEY_ID")
        logger.error("❌ Key ID не указан")
        logger.error("💡 Укажите через --key-id или установите переменную окружения RUSTORE_KEY_ID")
        logger.error("💡 Key ID можно получить в консоли разработчика RuStore при создании ключа")
    
    if missing_params:
        logger.error("=" * 60)
        logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: Отсутствуют обязательные параметры")
        logger.error(f"   Отсутствующие параметры: {', '.join(missing_params)}")
        logger.error("=" * 60)
        logger.error("💡 Для GitHub Actions добавьте секреты в настройках репозитория:")
        logger.error("   Settings → Secrets and variables → Actions → New repository secret")
        sys.exit(1)
    
    # Дополнительная валидация параметров
    if not package_name.strip():
        logger.error("❌ Package name пустой")
        sys.exit(1)
    
    if not private_key_str.strip():
        logger.error("❌ Приватный ключ пустой")
        sys.exit(1)
    
    # Публикуем APK
    success = publish_apk_to_rustore(apk_path, private_key_str, package_name, key_id)
    
    if not success:
        logger.error("❌ Публикация не удалась")
        sys.exit(1)
    
    logger.info("✅ Публикация успешно завершена")


if __name__ == "__main__":
    main()
