from ultralytics import YOLO
from pathlib import Path

# Определяем корень проекта (папка AI Food)
project_root = Path(__file__).parent.parent

# Путь к конфигурационному файлу датасета (yolo.yaml)
yaml_path = project_root / "datasets" / "Food (Yolo)" / "yolo.yaml"

# Проверяем, существует ли файл
if not yaml_path.exists():
    raise FileNotFoundError(f"Файл конфигурации не найден: {yaml_path}")

# Путь для сохранения результатов (в корне проекта, папка runs/segment)
results_dir = project_root / "runs" / "segment"

# Загружаем модель.
model = YOLO("yolo26m-seg.pt")  # или замените на "yolov8m-seg.pt", если нужно

# Запускаем обучение
model.train(
    data=str(yaml_path),          # путь к YAML-файлу датасета
    epochs=150,                    # количество эпох
    imgsz=640,                      # размер входного изображения
    batch=32,                        # размер батча (можно уменьшить, если не хватает памяти)
    device=0,                        # GPU (0 - первый)
    workers=6,                        # количество потоков загрузки данных
    patience=50,                      # ранняя остановка, если нет улучшений
    project=str(results_dir),        # папка для сохранения результатов
    name="food_seg",                  # имя эксперимента
    exist_ok=True,                    # перезаписывать папку, если существует
    pretrained=True,                  # использовать предобученные веса
    optimizer="auto",                  # автоматический выбор оптимизатора
    cos_lr=True,                       # косинусное затухание learning rate
    augment=True,                      # использовать аугментации
)