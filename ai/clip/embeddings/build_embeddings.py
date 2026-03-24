import os
import torch
import numpy as np
import open_clip
from PIL import Image
from tqdm import tqdm
from collections import defaultdict

#Перегонка изображений-текст в численно-векторный формат для последующего шага
#в цепочке CLIP > FAISS. Нужен для детекта похожих объектов и лучшего распознавания

DATASET_PATH = "datasets/food + recipes (CLIP)/images"
OUTPUT_FILE = "ai/clip/embeddings/food_embeddings.npy"
LABELS_FILE = "ai/clip/embeddings/food_labels.npy"

device = "cuda" if torch.cuda.is_available() else "cpu"

model, _, preprocess = open_clip.create_model_and_transforms(
    "ViT-L-14",
    pretrained="openai"
)
model = model.to(device)
model.eval()

#Группировка embeddings по классам > меньше шумма, лучше распознавание классов
class_embeddings = defaultdict(list)
print("Building embeddings...")
for folder in tqdm(os.listdir(DATASET_PATH)):
    folder_path = os.path.join(DATASET_PATH, folder)
    if not os.path.isdir(folder_path):
        continue
    label = folder.split("-")[-1].strip()
    for img_name in os.listdir(folder_path):
        img_path = os.path.join(folder_path, img_name)
        try:
            image = preprocess(Image.open(img_path).convert("RGB")).unsqueeze(0).to(device)
            with torch.no_grad():
                feat = model.encode_image(image)
            feat = feat / feat.norm(dim=-1, keepdim=True)
            feat = feat.cpu().numpy()[0]
            class_embeddings[label].append(feat)
        except:
            continue

#Создание centroid embeddings > вместо N изображений -- усредненное одно, повышение точности 
final_embeddings = []
final_labels = []
print("Averaging embeddings...")
for label, feats in class_embeddings.items():
    feats = np.array(feats)
    centroid = feats.mean(axis=0)
    centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
    final_embeddings.append(centroid)
    final_labels.append(label)
final_embeddings = np.array(final_embeddings).astype("float32")

np.save(OUTPUT_FILE, final_embeddings)
np.save(LABELS_FILE, final_labels)

print("Done!")
print("Classes:", len(final_labels))
print("Embeddings shape:", final_embeddings.shape)