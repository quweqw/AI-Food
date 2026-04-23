import torch
import open_clip

_clip_model = None
_tokenizer = None
_preprocess = None

def get_clip(model_name="ViT-L-14"):
    global _clip_model, _tokenizer, _preprocess

    if _clip_model is None:
        import open_clip
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"

        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name,
            pretrained="openai"
        )

        tokenizer = open_clip.get_tokenizer(model_name)

        model = model.to(device)
        model.eval()

        _clip_model = model
        _tokenizer = tokenizer
        _preprocess = preprocess

    return _clip_model, _tokenizer, _preprocess