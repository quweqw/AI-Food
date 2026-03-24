import numpy as np
import json
import faiss
import torch
import open_clip
from pathlib import Path

class FoodNormalizer:
    def __init__(self):
        BASE_DIR = Path(__file__).resolve().parent

        # Загружаем словарь ингредиентов
        self.vocab = json.load(open(BASE_DIR / "vocab.json"))

        # Загружаем эмбеддинги ингредиентов
        self.embeddings = np.load(BASE_DIR / "embed_vocab.npy").astype("float32")

        # Создаем FAISS индекс
        dim = self.embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dim)
        self.index.add(self.embeddings)

        # Загружаем CLIP для возможности дальнейшей нормализации
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model, _, _ = open_clip.create_model_and_transforms("ViT-L-14", pretrained="openai")
        self.model = self.model.to(self.device)
        self.model.eval()
        self.tokenizer = open_clip.get_tokenizer("ViT-L-14")

    def normalize(self, clip_embedding, top_k=3, threshold=0.25):
        """
        Нормализует эмбеддинг объекта пищи к словарю ингредиентов.
        Возвращает список словарей: [{"name": ingredient_name, "score": similarity}, ...]
        """
        clip_embedding = clip_embedding.astype("float32").reshape(1, -1)
        D, I = self.index.search(clip_embedding, top_k)

        results = []
        for score, idx in zip(D[0], I[0]):
            if score > threshold:
                results.append({
                    "name": self.vocab[idx],
                    "score": float(score)
                })

        return results

    def get_main_food(self, results):
        """Возвращает наиболее вероятный ингредиент"""
        if not results:
            return "unknown"
        return results[0]["name"]

    def extract_ingredients(self, all_normalized):
        """Возвращает список уникальных ингредиентов из всех результатов"""
        ingredients = set()
        for normalized_results in all_normalized:
            for item in normalized_results:
                ingredients.add(item["name"])
        return list(ingredients)

    def aggregate(self, all_results):
        """
        Агрегирует результаты нормализации по всем найденным объектам.
        Возвращает список кортежей (name, score) отсортированных по суммарному score.
        """
        from collections import defaultdict

        scores = defaultdict(float)

        for results in all_results:
            for r in results:
                scores[r["name"]] += r["score"]

        # сортируем по убыванию score
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_scores