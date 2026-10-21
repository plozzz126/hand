import unittest
from unittest.mock import Mock, call

import cv2

from gesture_lab.camera import configure_capture


class CaptureSettingsTests(unittest.TestCase):
    def test_720p_mjpeg_has_two_buffers_to_avoid_halving_capture_fps(self):
        capture = Mock()

        configure_capture(capture)

        self.assertEqual(capture.set.call_args_list, [
            call(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")),
            call(cv2.CAP_PROP_FRAME_WIDTH, 1280),
            call(cv2.CAP_PROP_FRAME_HEIGHT, 720),
            call(cv2.CAP_PROP_FPS, 30),
            call(cv2.CAP_PROP_BUFFERSIZE, 2),
        ])
        capture.read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
