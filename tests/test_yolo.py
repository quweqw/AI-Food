from ultralytics import YOLO
from pathlib import Path

# модель
model = YOLO("yolo26m-seg.pt")

# путь к картинке
img_path = Path(__file__).parent / "bus.jpg"  # тестовая картинка рядом с тестом

# абсолютный путь для результатов (от корня проекта)
save_dir = Path(__file__).resolve().parent.parent / "ai/yolo_results"

# запуск
results = model(str(img_path), save=True, device=0, save_dir=str(save_dir))

# Проверим, есть ли маски
if results[0].masks is not None:
    print(f"Найдено масок: {len(results[0].masks)}")
else:
    print("Модель не вернула маски.")