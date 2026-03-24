import torch
import open_clip
from PIL import Image

# выбираем устройство
device = "cuda" if torch.cuda.is_available() else "cpu"
print("Device:", device)

# загрузка модели CLIP
model, preprocess, _ = open_clip.create_model_and_transforms(
    "ViT-L-14",
    pretrained="laion2b_s32b_b82k"
)

# перенос модели на GPU
model = model.to(device)

# tokenizer
tokenizer = open_clip.get_tokenizer("ViT-L-14")

print("CLIP loaded successfully")