import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gesture_lab.camera_controls import apply_camera_profile


class CameraProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.profile = Path(self.directory.name) / "camera_profile.json"
        self.profile.write_text(json.dumps({
            "device_id": "test-camera",
            "controls": {"auto_exposure": 1, "exposure_time_absolute": 200, "sharpness": 3},
            "auto_controls": {"auto_exposure": 3, "sharpness": 2},
        }), encoding="utf-8")
        self.patches = [
            patch("gesture_lab.camera_controls.PROFILE_PATH", self.profile),
            patch("gesture_lab.camera_controls.sys.platform", "linux"),
            patch("gesture_lab.camera_controls.shutil.which", return_value="/usr/bin/v4l2-ctl"),
            patch("gesture_lab.camera_controls.matches_device", return_value=True),
            patch("gesture_lab.camera_controls.subprocess.run"),
        ]
        self.mocks = [context.start() for context in self.patches]

    def tearDown(self):
        for context in reversed(self.patches):
            context.stop()
        self.directory.cleanup()

    def test_exposure_mode_is_applied_before_manual_shutter(self):
        self.assertTrue(apply_camera_profile(0))
        commands = [call.args[0] for call in self.mocks[-1].call_args_list]
        self.assertEqual(commands[0][-1], "--set-ctrl=auto_exposure=1")
        self.assertIn("exposure_time_absolute=200", commands[1][-1])

    def test_automatic_profile_restores_original_controls(self):
        self.assertTrue(apply_camera_profile(0, tuned=False))
        commands = [call.args[0] for call in self.mocks[-1].call_args_list]
        self.assertEqual(commands[0][-1], "--set-ctrl=auto_exposure=3")
        self.assertEqual(commands[1][-1], "--set-ctrl=sharpness=2")

    def test_another_camera_is_not_modified(self):
        self.mocks[-2].return_value = False
        self.assertFalse(apply_camera_profile(1))
        self.mocks[-1].assert_not_called()

    def test_missing_v4l_tool_is_a_noop(self):
        self.mocks[2].return_value = None
        self.assertFalse(apply_camera_profile(0))
        self.mocks[-1].assert_not_called()

    def test_profile_failure_reports_error_without_stopping_camera(self):
        self.mocks[-1].side_effect = subprocess.TimeoutExpired("v4l2-ctl", 3)
        messages = []
        with self.assertLogs("gesture_lab.camera_controls", level="WARNING"):
            self.assertFalse(apply_camera_profile(0, status=messages.append))
        self.assertIn("Профиль камеры не применён", messages[0])


if __name__ == "__main__":
    unittest.main()
