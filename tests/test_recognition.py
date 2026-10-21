import threading
import unittest
from unittest.mock import Mock, call, patch

from gesture_lab.recognition import RecognitionPipeline, create_recognizer


class RecognizerFactoryTests(unittest.TestCase):
    @patch("gesture_lab.recognition._build_recognizer")
    def test_gpu_is_preferred_without_changing_the_model(self, build):
        recognizer, backend = create_recognizer("model.task")
        self.assertIs(recognizer, build.return_value)
        self.assertEqual(backend, "GPU")
        build.assert_called_once_with("model.task", "GPU")

    @patch("gesture_lab.recognition._build_recognizer")
    def test_gpu_initialization_failure_falls_back_to_cpu(self, build):
        cpu = object()
        build.side_effect = [RuntimeError("No EGL context"), cpu]
        with self.assertLogs("gesture_lab.recognition", level="WARNING"):
            recognizer, backend = create_recognizer("model.task")
        self.assertIs(recognizer, cpu)
        self.assertEqual(backend, "CPU")
        self.assertEqual(build.call_args_list, [call("model.task", "GPU"), call("model.task", "CPU")])

    @patch("gesture_lab.recognition._build_recognizer")
    def test_cpu_can_be_selected_explicitly(self, build):
        _, backend = create_recognizer("model.task", use_gpu=False)
        self.assertEqual(backend, "CPU")
        build.assert_called_once_with("model.task", "CPU")

    @patch("gesture_lab.recognition._build_recognizer", side_effect=RuntimeError("invalid model"))
    def test_cpu_failure_is_not_hidden(self, build):
        with (
            self.assertLogs("gesture_lab.recognition", level="WARNING"),
            self.assertRaisesRegex(RuntimeError, "invalid model"),
        ):
            create_recognizer("model.task")


class RecognitionPipelineTests(unittest.TestCase):
    def test_results_remain_attached_to_their_original_frames_and_timestamps(self):
        recognize = Mock(side_effect=lambda frame, timestamp: frame.upper())
        with RecognitionPipeline(recognize) as pipeline:
            self.assertIsNone(pipeline.submit("first", 1.0))
            self.assertEqual(pipeline.submit("second", 1.034), ("first", "FIRST", 1.0))
            self.assertEqual(pipeline.submit("third", 1.068), ("second", "SECOND", 1.034))
            pipeline.pending[2].result(timeout=1)
        self.assertEqual(recognize.call_args_list, [
            call("first", 1000), call("second", 1034), call("third", 1068),
        ])
        self.assertIsNone(pipeline.pending)

    def test_mediapipe_timestamps_are_strictly_increasing(self):
        recognize = Mock()
        with RecognitionPipeline(recognize) as pipeline:
            for timestamp in (1, 1, 1.0001, 1.034):
                pipeline.submit("frame", timestamp)
            pipeline.pending[2].result(timeout=1)
        self.assertEqual([args.args[1] for args in recognize.call_args_list], [1000, 1001, 1002, 1034])

    def test_next_inference_overlaps_rendering_without_a_frame_backlog(self):
        started = threading.Event()
        release = threading.Event()

        def recognize(frame, timestamp):
            if frame == "second":
                started.set()
                if not release.wait(2):
                    raise TimeoutError("test did not release inference")
            return frame

        with RecognitionPipeline(recognize) as pipeline:
            pipeline.submit("first", 1)
            completed = pipeline.submit("second", 1.034)
            try:
                self.assertEqual(completed, ("first", "first", 1))
                self.assertTrue(started.wait(1))
                self.assertEqual(pipeline.pending[:2], ("second", 1.034))
                self.assertFalse(pipeline.pending[2].done())
            finally:
                release.set()

    def test_inference_errors_propagate_instead_of_replaying_an_old_result(self):
        recognize = Mock(side_effect=RuntimeError("inference failed"))
        with RecognitionPipeline(recognize) as pipeline:
            pipeline.submit("first", 1)
            with self.assertRaisesRegex(RuntimeError, "inference failed"):
                pipeline.submit("second", 1.034)
        self.assertIsNone(pipeline.pending)


if __name__ == "__main__":
    unittest.main()
