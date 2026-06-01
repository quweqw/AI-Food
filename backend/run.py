import sys
import os

# Добавляем корень проекта в путь — до всех импортов
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,  # ← порт для back
        reload=True,
        reload_dirs=[os.path.dirname(os.path.abspath(__file__))]
    )