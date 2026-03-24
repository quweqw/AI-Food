import argparse
from pathlib import Path
import yaml
import os
from PIL import Image
import sys

# ------------------------------------------------------------
#  Проверка YOLO-датасета
# ------------------------------------------------------------
def check_yolo_dataset(dataset_path):
    """
    Проверяет структуру YOLO-датасета (поддерживает как детекцию, так и сегментацию)
    """
    dataset_path = Path(dataset_path)
    print(f"\n🔍 Проверка YOLO-датасета: {dataset_path}")

    yaml_files = list(dataset_path.glob("*.yaml"))
    if not yaml_files:
        print("❌ Не найден YAML-файл конфигурации (*.yaml)")
        return False
    yaml_path = yaml_files[0]
    print(f"   Используется конфиг: {yaml_path.name}")

    with open(yaml_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # Корень датасета — переданный путь (игнорируем path из YAML)
    root = dataset_path

    train_img_dir = root / config.get('train', 'train/images')
    val_img_dir = root / config.get('val', 'val/images')

    for name, img_dir in [("train", train_img_dir), ("val", val_img_dir)]:
        print(f"\n--- {name.upper()} ---")
        if not img_dir.exists():
            print(f"❌ Папка не найдена: {img_dir}")
            continue

        label_dir = img_dir.parent / 'labels'   # исправленный путь
        if not label_dir.exists():
            print(f"❌ Папка с метками не найдена: {label_dir}")
            continue

        img_files = sorted(img_dir.glob('*.*'))
        label_files = sorted(label_dir.glob('*.txt'))

        print(f"   Изображений: {len(img_files)}")
        print(f"   Файлов меток: {len(label_files)}")

        img_stems = {f.stem for f in img_files}
        label_stems = {f.stem for f in label_files}

        missing_labels = img_stems - label_stems
        missing_images = label_stems - img_stems

        if missing_labels:
            print(f"   ⚠️  Для {len(missing_labels)} изображений нет меток (первые 5): {list(missing_labels)[:5]}")
        else:
            print("   ✅ Все изображения имеют метки")

        if missing_images:
            print(f"   ⚠️  Найдено {len(missing_images)} меток без изображений (первые 5): {list(missing_images)[:5]}")
        else:
            print("   ✅ Все метки соответствуют изображениям")

        # Проверка формата меток (первые 100 файлов)
        print("\n   Проверка формата меток (первые 100 файлов):")
        errors = 0
        for i, lbl_file in enumerate(label_files):
            if i >= 100:
                break
            with open(lbl_file, 'r') as f:
                lines = f.readlines()
            for line_num, line in enumerate(lines):
                parts = line.strip().split()
                if len(parts) < 3:
                    print(f"   ❌ {lbl_file.name}:{line_num+1} строка слишком короткая: {line.strip()}")
                    errors += 1
                    continue
                try:
                    class_id = int(parts[0])
                    coords = list(map(float, parts[1:]))
                    if len(coords) % 2 != 0:
                        print(f"   ❌ {lbl_file.name}:{line_num+1} нечетное количество координат (должно быть четным): {line.strip()}")
                        errors += 1
                        continue
                    for coord in coords:
                        if not (0 <= coord <= 1):
                            print(f"   ❌ {lbl_file.name}:{line_num+1} координата {coord} вне диапазона [0,1] в строке: {line.strip()}")
                            errors += 1
                            break
                except ValueError:
                    print(f"   ❌ {lbl_file.name}:{line_num+1} ошибка преобразования чисел в строке: {line.strip()}")
                    errors += 1
        if errors == 0:
            print("   ✅ Формат меток корректен (первые 100 файлов)")
        else:
            print(f"   ⚠️  Найдено {errors} ошибок в формате меток")

        # Проверка целостности изображений (первые 100)
        print("\n   Проверка целостности изображений (первые 100):")
        corrupt = 0
        for i, img_file in enumerate(img_files):
            if i >= 100:
                break
            try:
                with Image.open(img_file) as im:
                    im.verify()
            except Exception as e:
                print(f"   ❌ {img_file.name}: повреждено -> {e}")
                corrupt += 1
        if corrupt == 0:
            print("   ✅ Все проверенные изображения открываются")
        else:
            print(f"   ⚠️  Найдено {corrupt} повреждённых изображений")

    print("\n✅ Проверка YOLO-датасета завершена.")
    return True

# ------------------------------------------------------------
#  Проверка CLIP-датасета (заготовка)
# ------------------------------------------------------------
def check_clip_dataset(dataset_path):
    """
    Проверяет структуру датасета для CLIP:
    - наличие папки с изображениями
    - наличие файла с текстовыми аннотациями (CSV/JSON)
    - соответствие количества изображений и записей
    - (можно добавить проверку формата captions)
    """
    dataset_path = Path(dataset_path)
    print(f"\n🔍 Проверка CLIP-датасета: {dataset_path}")

    # Ищем изображения (предполагаем, что они в подпапке images/)
    img_dir = dataset_path / 'images'
    if not img_dir.exists():
        print("❌ Не найдена папка 'images'")
        return False
    img_files = list(img_dir.glob('*.*'))
    print(f"   Найдено изображений: {len(img_files)}")

    # Ищем файл аннотаций (пробуем разные расширения)
    ann_files = list(dataset_path.glob('*.csv')) + list(dataset_path.glob('*.json')) + list(dataset_path.glob('*.txt'))
    if not ann_files:
        print("❌ Не найден файл аннотаций (.csv, .json, .txt)")
        return False
    ann_file = ann_files[0]
    print(f"   Найден файл аннотаций: {ann_file.name}")

    # Здесь можно добавить проверку формата в зависимости от расширения
    # Пока только базовая проверка на количество строк
    try:
        if ann_file.suffix == '.csv':
            import pandas as pd
            df = pd.read_csv(ann_file)
            print(f"   Записей в CSV: {len(df)}")
        elif ann_file.suffix == '.json':
            import json
            with open(ann_file, 'r') as f:
                data = json.load(f)
            print(f"   Записей в JSON: {len(data)}")
        elif ann_file.suffix == '.txt':
            with open(ann_file, 'r') as f:
                lines = f.readlines()
            print(f"   Строк в TXT: {len(lines)}")
    except Exception as e:
        print(f"❌ Ошибка при чтении файла аннотаций: {e}")
        return False

    print("\n✅ Базовая проверка CLIP-датасета завершена (требуется дополнительная настройка под конкретный формат).")
    return True

# ------------------------------------------------------------
#  Основная часть
# ------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Универсальная проверка датасетов (YOLO / CLIP)")
    parser.add_argument("--type", choices=["yolo", "clip"], help="Тип датасета")
    parser.add_argument("--path", type=str, help="Путь к папке датасета")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent  # папка, где лежит скрипт
    project_root = script_dir.parent if script_dir.name == "tests" else script_dir
    datasets_root = project_root / "datasets"

    if not args.type:
        args.type = input("Введите тип датасета (yolo/clip): ").strip().lower()

    if not args.path:
        if datasets_root.exists():
            print(f"Доступные датасеты в {datasets_root}:")
            for d in datasets_root.iterdir():
                if d.is_dir():
                    print(f"  - {d.name}")
            # Предлагаем путь по умолчанию
            default_path = datasets_root / "food (Yolo)"
            if default_path.exists():
                print(f"Найден датасет по умолчанию: {default_path}")
                use_default = input("Использовать этот датасет? (y/n): ").strip().lower()
                if use_default == 'y':
                    args.path = str(default_path)
        if not args.path:
            args.path = input("Введите путь к папке датасета: ").strip()

    dataset_path = Path(args.path)

    # --- ВЫЗОВ ПРОВЕРКИ ---
    if args.type == "yolo":
        check_yolo_dataset(dataset_path)
    elif args.type == "clip":
        check_clip_dataset(dataset_path)
    else:
        print("Неизвестный тип датасета. Используйте 'yolo' или 'clip'.")