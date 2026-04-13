import json
import os

from aiogram.types import FSInputFile, Message
from loguru import logger


class MediaManager:
    def __init__(self, assets_dir="src/presentation/assets", cache_file="banners_cache.json"):
        self.assets_dir = assets_dir
        self.cache_file = cache_file
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        """Загружает сохраненные file_id из файла"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load media cache: {e}")
        return {}

    def _save_cache(self):
        """Сохраняет file_id в файл"""
        with open(self.cache_file, "w") as f:
            json.dump(self.cache, f)

    def get(self, filename: str):
        """
        Возвращает быстрый file_id (если фото уже загружалось),
        либо FSInputFile (если это первый запуск).
        """
        if filename in self.cache:
            return self.cache[filename]
        
        file_path = os.path.join(self.assets_dir, filename)
        if not os.path.exists(file_path):
            logger.error(f"Banner not found on disk: {file_path}")
            # Можно подставить заглушку или вернуть None, чтобы бот не падал
            raise FileNotFoundError(f"Missing asset: {file_path}")
            
        return FSInputFile(file_path)

    def save_from_message(self, filename: str, message: Message):
        """Извлекает file_id из отправленного сообщения и кэширует его"""
        if message.photo:
            # берем [-1], так как это самое высокое качество
            file_id = message.photo[-1].file_id 
            self.cache[filename] = file_id
            self._save_cache()
            logger.success(f"Cached file_id for {filename}")

# Создаем глобальный объект (Singleton)
media = MediaManager()