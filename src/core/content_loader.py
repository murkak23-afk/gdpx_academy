import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import aiofiles
from src.core.logger import logger

@dataclass(frozen=True)
class FaqCard:
    id: str
    emoji: str
    title: str
    text: str

@dataclass(frozen=True)
class ManualCard:
    id: str
    emoji: str
    title: str
    text: str
    level: str = "base"

@dataclass(frozen=True)
class ManualLevel:
    id: str
    emoji: str
    title: str

class ContentLoader:
    def __init__(self):
        self._faq_cards: Tuple[FaqCard, ...] = ()
        self._faq_by_id: Dict[str, FaqCard] = {}
        self._manuals: Tuple[ManualCard, ...] = ()
        self._manual_levels: Tuple[ManualLevel, ...] = ()
        self._manuals_by_id: Dict[str, ManualCard] = {}
        self._divider: str = "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰"

    async def load_all(self):
        """Loads all content from JSON files."""
        await self._load_faq()
        await self._load_manuals()

    async def _load_faq(self):
        path = "data/content/faq/cards.json"
        try:
            async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
                content = await f.read()
                data = json.loads(content)
                
                divider = data.get("divider", self._divider)
                self._divider = divider
                
                cards = []
                for card_data in data.get("cards", []):
                    # Inject divider if placeholder exists
                    text = card_data["text"].replace("{divider}", divider)
                    card = FaqCard(
                        id=card_data["id"],
                        emoji=card_data["emoji"],
                        title=card_data["title"],
                        text=text
                    )
                    cards.append(card)
                
                self._faq_cards = tuple(cards)
                self._faq_by_id = {card.id: card for card in self._faq_cards}
                logger.info(f"Loaded {len(self._faq_cards)} FAQ cards from {path}")
        except Exception as e:
            logger.error(f"Failed to load FAQ from {path}: {e}")
            raise RuntimeError(f"Critical error loading FAQ: {e}")

    async def _load_manuals(self):
        levels_path = "data/content/manuals/levels.json"
        cards_path = "data/content/manuals/cards.json"
        
        try:
            # Load Levels
            async with aiofiles.open(levels_path, mode="r", encoding="utf-8") as f:
                levels_data = json.loads(await f.read())
                self._manual_levels = tuple(ManualLevel(**lvl) for lvl in levels_data.get("levels", []))
            
            # Load Cards
            async with aiofiles.open(cards_path, mode="r", encoding="utf-8") as f:
                data = json.loads(await f.read())
                divider = data.get("divider", self._divider)
                
                manuals = []
                for m_data in data.get("cards", []):
                    text = m_data["text"].replace("{divider}", divider)
                    manual = ManualCard(
                        id=m_data["id"],
                        emoji=m_data["emoji"],
                        title=m_data["title"],
                        text=text,
                        level=m_data.get("level", "base")
                    )
                    manuals.append(manual)
                
                self._manuals = tuple(manuals)
                self._manuals_by_id = {m.id: m for m in self._manuals}
                logger.info(f"Loaded {len(self._manuals)} manuals from {cards_path}")
        except Exception as e:
            logger.error(f"Failed to load manuals: {e}")
            raise RuntimeError(f"Critical error loading manuals: {e}")

    async def reload(self):
        """Hot reload content."""
        logger.info("Hot reloading content...")
        await self.load_all()

    @property
    def faq_cards(self) -> Tuple[FaqCard, ...]:
        return self._faq_cards

    def get_faq_by_id(self, faq_id: str) -> Optional[FaqCard]:
        return self._faq_by_id.get(faq_id)

    @property
    def manuals(self) -> Tuple[ManualCard, ...]:
        return self._manuals

    @property
    def manual_levels(self) -> Tuple[ManualLevel, ...]:
        return self._manual_levels

    def get_manual_by_id(self, manual_id: str) -> Optional[ManualCard]:
        return self._manuals_by_id.get(manual_id)

    def get_manuals_by_level(self, level_id: str) -> Tuple[ManualCard, ...]:
        return tuple(m for m in self._manuals if m.level == level_id)

    def get_divider(self) -> str:
        return self._divider

# Global instance
loader = ContentLoader()

async def init_content():
    await loader.load_all()

async def reload_content():
    await loader.reload()

def get_faq_cards() -> Tuple[FaqCard, ...]:
    return loader.faq_cards

def get_faq_by_id(faq_id: str) -> Optional[FaqCard]:
    return loader.get_faq_by_id(faq_id)

def get_manuals() -> Tuple[ManualCard, ...]:
    return loader.manuals

def get_manual_levels() -> Tuple[ManualLevel, ...]:
    return loader.manual_levels

def get_manual_by_id(manual_id: str) -> Optional[ManualCard]:
    return loader.get_manual_by_id(manual_id)

def get_manuals_by_level(level_id: str) -> Tuple[ManualCard, ...]:
    return loader.get_manuals_by_level(level_id)

def get_divider() -> str:
    return loader.get_divider()
