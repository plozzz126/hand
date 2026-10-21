import json
import math
import os
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
MODEL_PATH = ROOT / "models" / "gesture_recognizer.task"
GIF_DIR = ROOT / "assets" / "gifs"

GESTURES = {
    "Open_Palm": ("Ладонь", "Раскрой все пять пальцев", "portal"),
    "Victory": ("Победа / V", "Подними указательный и средний", "confetti"),
    "Thumb_Up": ("Лайк", "Большой палец вверх", "sparks"),
    "Thumb_Down": ("Дизлайк", "Большой палец вниз", "rain"),
    "Pointing_Up": ("Указательный", "Один указательный палец вверх", "orbit"),
    "ILoveYou": ("I love you", "Большой, указательный и мизинец", "hearts"),
    "Closed_Fist": ("Кулак", "Сожми ладонь в кулак", "clear"),
    "Pinch": ("Щипок", "Соедини большой и указательный; остальные раскрой", "pulse"),
    "Swipe_Left": ("Взмах влево", "Быстро сдвинь открытую ладонь влево", "rain"),
    "Swipe_Right": ("Взмах вправо", "Быстро сдвинь открытую ладонь вправо", "confetti"),
}

EFFECTS = {
    "portal": "Неоновый портал",
    "confetti": "Конфетти",
    "sparks": "Искры",
    "rain": "Неоновый дождь",
    "orbit": "Орбиты",
    "hearts": "Сердца",
    "pulse": "Пульс",
    "clear": "Очистить сцену",
}

DEFAULT_CONFIG = {
    "camera_index": 0,
    "mirror": True,
    "camera_tuned": True,
    "gpu_acceleration": True,
    "confidence": 0.65,
    "hold_ms": 350,
    "cooldown_ms": 1000,
    "bindings": {
        gesture: {"type": "effect", "value": details[2]}
        for gesture, details in GESTURES.items()
    },
}


def validate_config(data):
    if not isinstance(data, dict):
        raise TypeError("Корень config.json должен быть объектом")
    result = deepcopy(DEFAULT_CONFIG)
    for key, lower, upper in (
        ("camera_index", 0, 99),
        ("confidence", 0.1, 1.0),
        ("hold_ms", 0, 2000),
        ("cooldown_ms", 0, 10000),
    ):
        value = data.get(key, result[key])
        expected_type = (int, float) if key == "confidence" else (int,)
        if (
            isinstance(value, bool)
            or not isinstance(value, expected_type)
            or not math.isfinite(value)
            or not lower <= value <= upper
        ):
            raise ValueError(f"Недопустимое значение {key}: {value}")
        result[key] = value
    for key in ("mirror", "camera_tuned", "gpu_acceleration"):
        if key in data:
            if not isinstance(data[key], bool):
                raise ValueError(f"{key} должен быть true или false")
            result[key] = data[key]
    bindings = data.get("bindings", {})
    if not isinstance(bindings, dict):
        raise TypeError("bindings должен быть объектом")
    for gesture, binding in bindings.items():
        if gesture not in GESTURES:
            raise ValueError(f"Неизвестный жест: {gesture}")
        if not isinstance(binding, dict):
            raise TypeError(f"Некорректное действие: {gesture}")
        action_type, value = binding.get("type"), binding.get("value")
        if not isinstance(value, str) or not (
            (action_type == "effect" and value in EFFECTS)
            or (action_type == "gif" and value.strip())
        ):
            raise ValueError(f"Некорректное действие для {gesture}")
        result["bindings"][gesture] = {"type": action_type, "value": value}
    return result


def load_config(path=CONFIG_PATH):
    if not path.exists():
        return deepcopy(DEFAULT_CONFIG)
    with path.open(encoding="utf-8") as handle:
        return validate_config(json.load(handle))


def save_config(config, path=CONFIG_PATH):
    validated = validate_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(validated, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def resolve_asset(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path
