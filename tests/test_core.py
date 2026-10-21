import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gesture_lab.config import DEFAULT_CONFIG, load_config, save_config, validate_config
from gesture_lab.gestures import GestureGate, Observation, SwipeDetector, is_pinch
from gesture_lab.model import ensure_model, file_sha256


def landmarks(center_x=0.5):
    return [SimpleNamespace(x=center_x, y=0.5, z=0.0) for _ in range(21)]


class GestureGateTests(unittest.TestCase):
    def setUp(self):
        self.gate = GestureGate(hold_ms=300, cooldown_ms=600)
        self.palm = Observation("Open_Palm", 0.9, 1)

    def hold(self, observation, start, frames=5):
        return [self.gate.update(observation, start + index * 0.1) for index in range(frames)]

    def test_hold_triggers_once(self):
        events = self.hold(self.palm, 0, 25)
        self.assertEqual([event for event in events if event], ["Open_Palm"])

    def test_low_confidence_does_not_trigger(self):
        self.assertFalse(any(self.hold(Observation("Victory", 0.3, 1), 0, 10)))

    def test_release_rearms_same_gesture(self):
        self.hold(self.palm, 0)
        self.hold(Observation(), 0.5, 4)
        self.assertIn("Open_Palm", self.hold(self.palm, 0.9))

    def test_one_missing_frame_does_not_rearm(self):
        self.hold(self.palm, 0)
        self.gate.update(Observation(), 0.5)
        self.assertFalse(any(self.hold(self.palm, 0.6, 20)))

    def test_changed_gesture_can_trigger_without_removing_hand(self):
        self.hold(self.palm, 0)
        self.assertIn("Victory", self.hold(Observation("Victory", 0.95, 1), 0.5, 8))

    def test_camera_stall_restarts_hold(self):
        self.gate.update(self.palm, 0)
        self.gate.update(self.palm, 0.1)
        self.assertIsNone(self.gate.update(self.palm, 2))
        self.assertEqual(self.gate.progress, 0)

    def test_swipes_are_events_and_obey_cooldown(self):
        swipe = Observation("Open_Palm", 0.9, 1, "Swipe_Right")
        self.assertEqual(self.gate.update(swipe, 0), "Swipe_Right")
        self.assertIsNone(self.gate.update(swipe, 0.1))
        self.assertEqual(self.gate.update(swipe, 0.7), "Swipe_Right")


class LandmarkTests(unittest.TestCase):
    def test_swipe_direction(self):
        for direction, expected in ((1, "Swipe_Right"), (-1, "Swipe_Left")):
            detector = SwipeDetector()
            results = [detector.update(landmarks(0.5 + direction * index * 0.08),
                                      "Open_Palm", 0.95, "Left", index * 0.05)
                       for index in range(5)]
            self.assertIn(expected, results)

    def test_changed_hand_does_not_create_false_swipe(self):
        detector = SwipeDetector()
        detector.update(landmarks(0.2), "Open_Palm", 0.95, "Left", 0)
        detector.update(landmarks(0.21), "Open_Palm", 0.95, "Left", 0.05)
        self.assertIsNone(detector.update(landmarks(0.8), "Open_Palm", 0.95, "Right", 0.15))

    def test_missing_hand_resets_swipe(self):
        detector = SwipeDetector()
        detector.update(landmarks(0.2), "Open_Palm", 0.95, "Left", 0)
        detector.update([], None, 0, None, 0.05)
        self.assertIsNone(detector.update(landmarks(0.8), "Open_Palm", 0.95, "Left", 0.15))

    def test_pinch_requires_open_other_fingers(self):
        points = landmarks()
        points[0].y = 0.9
        points[9].y = 0.6
        for tip in (4, 8):
            points[tip].y = 0.5
        for tip in (12, 16, 20):
            points[tip].y = 0.2
        self.assertTrue(is_pinch(points))
        for tip in (12, 16, 20):
            points[tip].y = 0.8
        self.assertFalse(is_pinch(points))

    def test_degenerate_landmarks_are_not_pinch(self):
        self.assertFalse(is_pinch([]))
        self.assertFalse(is_pinch(landmarks()))


class ConfigurationTests(unittest.TestCase):
    def test_defaults_are_independent(self):
        first = validate_config({})
        first["bindings"]["Victory"]["value"] = "clear"
        self.assertEqual(validate_config({}), DEFAULT_CONFIG)

    def test_invalid_settings_are_rejected(self):
        for data in ([], {"hold_ms": -1}, {"mirror": "yes"}, {"camera_index": True},
                     {"gpu_acceleration": "yes"},
                     {"confidence": float("nan")}, {"bindings": []},
                     {"bindings": {"Victory": {"type": "effect", "value": []}}}):
            with self.subTest(data=data), self.assertRaises((ValueError, TypeError)):
                validate_config(data)

    def test_round_trip_with_gif(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = validate_config({"bindings": {"Victory": {"type": "gif", "value": "assets/gifs/test.gif"}}})
            save_config(config, path)
            self.assertEqual(load_config(path), config)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_invalid_json_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                load_config(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")


class ModelDownloadTests(unittest.TestCase):
    def test_file_hash_handles_multiple_blocks_without_python_311_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.task"
            content = b"model" * 30000
            path.write_bytes(content)
            self.assertEqual(file_sha256(path), hashlib.sha256(content).hexdigest())

    def test_valid_cached_model_never_uses_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.task"
            path.write_bytes(b"verified")
            digest = hashlib.sha256(b"verified").hexdigest()
            with patch("gesture_lab.model.MODEL_SHA256", digest), patch("urllib.request.urlopen") as request:
                self.assertEqual(ensure_model(path), path)
                request.assert_not_called()

    def test_bad_download_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.task"
            path.write_bytes(b"old")
            with (
                patch("urllib.request.urlopen", return_value=io.BytesIO(b"bad")),
                self.assertRaises(ValueError),
            ):
                ensure_model(path)
            self.assertEqual(path.read_bytes(), b"old")
            self.assertEqual(list(Path(directory).glob("*.part")), [])

    def test_download_cancellation_cleans_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.task"
            with (
                patch("urllib.request.urlopen", return_value=io.BytesIO(b"data")),
                self.assertRaises(InterruptedError),
            ):
                ensure_model(path, cancelled=lambda: True)
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
