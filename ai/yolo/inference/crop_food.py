import os
import cv2
import numpy as np
from ultralytics import YOLO

MODEL_PATH = "ai/yolo/models/food_yolo_seg.pt"
OUTPUT_DIR = "ai/yolo/results"

#Выделение распознаного объекта по сегменту с прозрачным фоном
#Yolo > Crop для последующего Crop > CLIP
model = YOLO(MODEL_PATH)


def crop_food(image_path):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    results = model(image_path)
    image = cv2.imread(image_path)

    if image is None:
        return []

    h, w = image.shape[:2]

    crops = []

    for result in results:
        if result.masks is None or result.boxes is None:
            continue

        masks = result.masks.data.cpu().numpy()
        boxes = result.boxes.xyxy.cpu().numpy()
        classes = result.boxes.cls.cpu().numpy()

        for i, mask in enumerate(masks):
            # resize mask
            mask = cv2.resize(mask, (w, h))
            mask = (mask > 0.5).astype(np.uint8)

            # alpha channel
            alpha = (mask * 255).astype(np.uint8)

            rgba = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
            rgba[:, :, 3] = alpha

            x1, y1, x2, y2 = boxes[i].astype(int)

            crop = rgba[y1:y2, x1:x2]

            # Получаем класс
            cls_id = int(classes[i])
            label = result.names[cls_id]

            conf = float(result.boxes.conf[i])
            filename = f"{label}_{i}_{int(conf*100)}.png"
            path = os.path.join(OUTPUT_DIR, filename)

            cv2.imwrite(path, crop)

            crops.append({
                "path": path,
                "label": label
            })
    return crops

if __name__ == "__main__":
    test_image = "tests/test.jpg"
    crops = crop_food(test_image)

    print("Saved crops:")
    for c in crops:
        print(c)