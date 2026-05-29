# ingredient_scorer.py
import logging
from collections import defaultdict

logger = logging.getLogger("IngredientScorer")

# Объединение баллов YOLO и CLIP. Формирование общей оценки уверенности
class IngredientScorer:

    def __init__(self, synonym_map=None, min_score=0.3):
        # базовые синонимы (потом вынести в /data/synonims.json)
        self.synonym_map = synonym_map or {
            "fries": "potato",
            "french fries": "potato",
            "chips": "potato",
            "pasta": "noodles",
            "spaghetti": "noodles",
            "shrimp": "shrimp",
            "prawn": "shrimp",
            "egg noodles": "noodles",
        }

        self.min_score = min_score

    # ==========================
    # Нормализация
    # ==========================
    def _normalize_label(self, label: str) -> str:
        if not label:
            return ""

        label = label.lower().strip()
        return self.synonym_map.get(label, label)

    # ==========================
    # Основная функция общей уверенности
    # ==========================
    def combine(self, yolo_labels, clip_normalized):
        """
        yolo_labels: list[str]
        clip_normalized: list[dict] -> [{"name": ..., "score": ...}]
        """

        scores = defaultdict(float)

        # ==========================
        # Оценки YOLO
        # ==========================
        for label in yolo_labels:
            norm = self._normalize_label(label)
            scores[norm] += 0.6  # Вес YOLO в общей оценке

        # ==========================
        # Оценки CLIP
        # ==========================
        for item in clip_normalized:
            if not isinstance(item, dict):
                continue

            name = item.get("name")
            score = item.get("score", 0)

            if not name:
                continue

            norm = self._normalize_label(name)
            scores[norm] += float(score) * 1.0  # Вес CLIP в общей оценке

        # ==========================
        # Подсчет
        # ==========================
        results = []

        for name, score in scores.items():
            if score >= self.min_score:
                results.append({
                    "name": name,
                    "score": round(score, 4)
                })

        # Сортировка по уверенности
        results.sort(key=lambda x: x["score"], reverse=True)

        logger.info(f"Scored ingredients: {results}")

        return results

    # ==========================
    # Строгое фильтрование (k - кол-во ближайших образцов к исходному)
    # ==========================
    def filter_top_k(self, ingredients, k=5):
        return sorted(
            ingredients,
            key=lambda x: x.get("score", 0),
            reverse=True
        )[:k]