import json
import numpy as np
import open_clip
import torch

device = "cuda" if torch.cuda.is_available() else "cpu"

model, _, preprocess = open_clip.create_model_and_transforms(
    "ViT-L-14", pretrained="openai"
)
tokenizer = open_clip.get_tokenizer("ViT-L-14")

model = model.to(device)
model.eval()

with open("ai/food_normalizer/vocab.json") as f:
    vocab = json.load(f)

text_tokens = tokenizer(vocab).to(device)

with torch.no_grad():
    text_features = model.encode_text(text_tokens)

text_features = text_features.cpu().numpy()
text_features /= np.linalg.norm(text_features, axis=1, keepdims=True)

np.save("ai/food_normalizer/embed_vocab.npy", text_features)

print("Done:", text_features.shape)