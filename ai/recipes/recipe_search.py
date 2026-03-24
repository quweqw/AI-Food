import json
import numpy as np
import faiss
import torch
import open_clip
from pathlib import Path

class RecipeSearch:
    def __init__(self):
        BASE_DIR = Path(__file__).resolve().parent
        self.recipes = json.load(open(BASE_DIR / "recipes.json"))
        self.index = faiss.read_index(str(BASE_DIR / "recipe_index.faiss"))
        self.embeddings = np.load(BASE_DIR / "recipe_embeddings.npy")

        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        self.model, _, _ = open_clip.create_model_and_transforms(
            "ViT-L-14",
            pretrained="openai"
        )
        self.model = self.model.to(self.device)
        self.model.eval()

        self.tokenizer = open_clip.get_tokenizer("ViT-L-14")

    def encode_query(self, text):
        with torch.no_grad():
            tokens = self.tokenizer([text]).to(self.device)
            emb = self.model.encode_text(tokens)
            emb = emb.cpu().numpy()

        emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-10)
        return emb.astype("float32")

    def search(self, query, top_k=3):
        emb = self.encode_query(query)

        D, I = self.index.search(emb, top_k)

        results = []
        for score, idx in zip(D[0], I[0]):
            recipe = self.recipes[idx]

            results.append({
                "name": recipe["name"],
                "ingredients": recipe["ingredients"],
                "instructions": recipe["instructions"],
                "score": float(score)
            })

        return results