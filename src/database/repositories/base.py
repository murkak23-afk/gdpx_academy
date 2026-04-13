from __future__ import annotations

from typing import Generic, Type, TypeVar, Sequence
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    def __init__(self, model: Type[ModelType], session: AsyncSession):
        self.model = model
        self.session = session

    async def get_by_id(self, id: int) -> ModelType | None:
        query = select(self.model).where(self.model.id == id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_all(self) -> Sequence[ModelType]:
        query = select(self.model)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def add(self, entity: ModelType) -> ModelType:
        self.session.add(entity)
        return entity

    async def delete(self, id: int) -> None:
        query = delete(self.model).where(self.model.id == id)
        await self.session.execute(query)

    async def update(self, id: int, **kwargs) -> None:
        query = update(self.model).where(self.model.id == id).values(**kwargs)
        await self.session.execute(query)
