import numpy as np
import faiss
import os

#Создание FAISS-индекса как быстрой поисковой базы данных.

EMBEDDINGS_PATH = "ai/clip/embeddings/food_embeddings.npy"
INDEX_PATH = "ai/clip/index/food_index.faiss"

print("Loading embeddings...")

embeddings = np.load(EMBEDDINGS_PATH).astype("float32")
dimension = embeddings.shape[1]

print("Embeddings shape:", embeddings.shape)
print("Creating FAISS index...")

index = faiss.IndexFlatIP(dimension) #Векторное сравнение
index.add(embeddings)

print("Total vectors in index:", index.ntotal)

os.makedirs("ai/clip/index", exist_ok=True)
faiss.write_index(index, INDEX_PATH)

print("Index saved to:", INDEX_PATH)