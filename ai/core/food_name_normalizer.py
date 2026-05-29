from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Union


class FoodNameNormalizer:
    """
    Единая нормализация названий продуктов.

    Пример:
    chicken_breast -> chicken
    chicken breast -> chicken
    eggs -> egg
    russet_potatoes -> potato
    salmon_fillet -> salmon
    """

    def __init__(self, data_dir: Optional[Union[str, Path]] = None):
        self.project_root = Path(__file__).resolve().parents[2]
        self.ai_dir = self.project_root / "ai"
        self.data_dir = Path(data_dir) if data_dir else self.ai_dir / "data"

        self.aliases = self._load_aliases()

    def _load_aliases(self) -> Dict[str, str]:
        path = self.data_dir / "food_aliases.json"

        if not path.exists():
            return {}

        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        if not isinstance(raw, dict):
            return {}

        aliases = {}

        for k, v in raw.items():
            key = self.normalize_key(k)
            value = self.normalize_key(v)
            if key and value:
                aliases[key] = value

        return aliases

    def normalize_key(self, value: Any) -> str:
        value = str(value or "").strip().lower()

        if not value:
            return ""

        value = value.replace("-", "_")
        value = value.replace("/", "_or_")
        value = value.replace("&", "and")

        # optional пометки убираем
        value = re.sub(r"\(optional\)", "", value)
        value = re.sub(r"\s+", " ", value).strip()

        # скобки убираем, но текст оставляем
        value = value.replace("(", "").replace(")", "")

        # пробелы -> _
        value = "_".join(value.split())

        # повторные подчёркивания
        value = re.sub(r"_+", "_", value).strip("_")

        return value

    def canonical(self, value: Any) -> str:
        key = self.normalize_key(value)

        if not key:
            return ""

        if key in self.aliases:
            return self.aliases[key]

        # простые fallback-правила
        if key.endswith("ies"):
            singular = key[:-3] + "y"
            if singular in self.aliases:
                return self.aliases[singular]

        if key.endswith("s"):
            singular = key[:-1]
            if singular in self.aliases:
                return self.aliases[singular]

        return key