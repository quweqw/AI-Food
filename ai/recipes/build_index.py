import json
import numpy as np
import faiss
import torch
import open_clip
from pathlib import Path

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# load model
model, _, _ = open_clip.create_model_and_transforms("ViT-L-14", pretrained="openai")
model = model.to(DEVICE)
model.eval()

tokenizer = open_clip.get_tokenizer("ViT-L-14")

# load recipes
BASE_DIR = Path(__file__).resolve().parent  # папка ai/recipes
recipes = json.load(open(BASE_DIR / "recipes.json"))

texts = []
for r in recipes:
    text = f"{r['name']} with {', '.join(r['ingredients'])}"
    texts.append(text)

# encode
with torch.no_grad():
    tokens = tokenizer(texts).to(DEVICE)
    embeddings = model.encode_text(tokens)
    embeddings = embeddings.cpu().numpy()

# normalize
embeddings = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-10)

# save embeddings and index in BASE_DIR
np.save(BASE_DIR / "recipe_embeddings.npy", embeddings)

index = faiss.IndexFlatIP(embeddings.shape[1])
index.add(embeddings)

faiss.write_index(index, str(BASE_DIR / "recipe_index.faiss"))

print("Recipe index built!")