from ultralytics import YOLO
model = YOLO("../runs/segment/train17/weights/best.pt")
results = model("test.jpg", show=True)