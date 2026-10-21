import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


def _build_recognizer(model, backend):
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    options = vision.GestureRecognizerOptions(
        base_options=python.BaseOptions(
            model_asset_path=str(model), delegate=getattr(python.BaseOptions.Delegate, backend),
        ),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return vision.GestureRecognizer.create_from_options(options)


def create_recognizer(model, use_gpu=True):
    if use_gpu:
        try:
            return _build_recognizer(model, "GPU"), "GPU"
        except (RuntimeError, ValueError, NotImplementedError) as error:
            logger.warning("GPU недоступен, использую CPU: %s", error)
    return _build_recognizer(model, "CPU"), "CPU"


class RecognitionPipeline:
    def __init__(self, recognize):
        self.recognize = recognize
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hand-inference")
        self.pending = None
        self.last_timestamp_ms = -1

    def __enter__(self):
        return self

    def submit(self, frame, timestamp):
        completed = None
        if self.pending is not None:
            previous_frame, previous_timestamp, future = self.pending
            completed = previous_frame, future.result(), previous_timestamp
        timestamp_ms = max(self.last_timestamp_ms + 1, int(timestamp * 1000))
        self.last_timestamp_ms = timestamp_ms
        future = self.executor.submit(self.recognize, frame, timestamp_ms)
        self.pending = frame, timestamp, future
        return completed

    def __exit__(self, error_type, error, traceback):
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.pending = None
