import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path

from gesture_lab.config import MODEL_PATH

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
    "gesture_recognizer/float16/1/gesture_recognizer.task"
)
MODEL_SHA256 = "97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482"


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_model(path=MODEL_PATH, status=lambda message: None, cancelled=lambda: False):
    if path.exists() and file_sha256(path) == MODEL_SHA256:
        return path
    status("Загружаю модель MediaPipe (~8 МБ)…")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".part")
    digest = hashlib.sha256()
    try:
        with (
            os.fdopen(descriptor, "wb") as handle,
            urllib.request.urlopen(MODEL_URL, timeout=10) as response,
        ):
            while chunk := response.read(65536):
                if cancelled():
                    raise InterruptedError("Загрузка отменена")
                handle.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != MODEL_SHA256:
            raise ValueError("Контрольная сумма модели не совпадает. Попробуй ещё раз.")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path
