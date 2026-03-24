import json
from pathlib import Path

# Пути к файлам
BASE_DIR = Path(__file__).resolve().parent
START_VOCAB_PATH = BASE_DIR / "start_vocab.json"
VOCAB_PATH = BASE_DIR / "vocab.json"

# 1. Загружаем сырой словарь
with open(START_VOCAB_PATH, "r", encoding="utf-8") as f:
    raw_vocab = json.load(f)

# 2. Убираем дубликаты и сортируем (по алфавиту)
unique_vocab = sorted(list(set(raw_vocab)))

# 3. Сохраняем готовый словарь в vocab.json с форматированием
with open(VOCAB_PATH, "w", encoding="utf-8") as f:
    json.dump(unique_vocab, f, ensure_ascii=False, indent=4)

print(f"Готовый словарь сохранён в {VOCAB_PATH}")