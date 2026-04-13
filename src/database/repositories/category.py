from __future__ import annotations

from src.database.models.category import Category
from src.database.repositories.base import BaseRepository


class CategoryRepository(BaseRepository[Category]):
    def __init__(self, session):
        super().__init__(Category, session)
