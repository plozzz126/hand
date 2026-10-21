import logging
import time
from dataclasses import dataclass
from threading import Lock

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from gesture_lab.activation import ContactToggle
from gesture_lab.camera_controls import apply_camera_profile
from gesture_lab.gestures import Observation, SwipeDetector, is_middle_finger, is_pinch
from gesture_lab.model import ensure_model
from gesture_lab.portal import PortalState, PortalTracker, render_portal
from gesture_lab.recognition import RecognitionPipeline, create_recognizer
from gesture_lab.tracking import HandTracker

logger = logging.getLogger(__name__)

CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)


def configure_capture(capture):
    import cv2

    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    capture.set(cv2.CAP_PROP_FPS, 30)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 2)


@dataclass(frozen=True)
class FramePacket:
    image: QImage
    observation: Observation
    fps: float
    timestamp: float
    portal: PortalState | None = None
    portal_enabled: bool = False
    contact_progress: float = 0.0
    contact_changed: bool = False
    backend: str = "CPU"


class CameraWorker(QThread):
    status = Signal(str)
    failed = Signal(str)

    def __init__(self, camera_index, mirror, parent=None, show_landmarks=True, tuned=True, use_gpu=True):
        super().__init__(parent)
        self.camera_index = camera_index
        self.mirror = mirror
        self.show_landmarks = show_landmarks
        self.tuned = tuned
        self.use_gpu = use_gpu
        self.paused = False
        self._lock = Lock()
        self._packet = None

    def take_packet(self):
        with self._lock:
            packet, self._packet = self._packet, None
        return packet

    def run(self):
        capture = None
        try:
            self.status.emit("Подготавливаю распознавание…")
            import cv2
            import mediapipe as mp

            cv2.setNumThreads(2)

            model = ensure_model(
                status=self.status.emit, cancelled=self.isInterruptionRequested
            )
            if self.isInterruptionRequested():
                return
            self.status.emit(f"Открываю камеру {self.camera_index}…")
            capture = cv2.VideoCapture(self.camera_index)
            if not capture.isOpened():
                raise RuntimeError(
                    f"Не удалось открыть камеру {self.camera_index}. "
                    "Закрой приложения, использующие камеру, или выбери другой индекс."
                )
            configure_capture(capture)
            apply_camera_profile(self.camera_index, self.tuned, self.status.emit)
            swipe = SwipeDetector()
            portal_tracker = PortalTracker()
            hand_tracker = HandTracker()
            activation = ContactToggle()
            previous_frame = time.monotonic()
            fps = 0.0
            recognizer, backend = create_recognizer(model, self.use_gpu)

            def recognize(rgb, timestamp_ms):
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                return recognizer.recognize_for_video(image, timestamp_ms)

            with recognizer, RecognitionPipeline(recognize) as pipeline:
                self.status.emit("Соедини два указательных и два больших пальца, затем разведи руки")
                while not self.isInterruptionRequested():
                    if self.paused:
                        self.msleep(80)
                        continue
                    success, frame = capture.read()
                    if not success:
                        raise RuntimeError("Камера перестала отдавать кадры. Подключи её и запусти снова.")
                    if self.mirror:
                        frame = cv2.flip(frame, 1)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    timestamp = time.monotonic()
                    completed = pipeline.submit(rgb, timestamp)
                    if completed is None:
                        continue
                    rgb, result, timestamp = completed
                    tracked_hands = hand_tracker.update(
                        result.hand_landmarks, result.handedness,
                        getattr(result, "hand_world_landmarks", ()), timestamp,
                    )
                    gesture, confidence = None, 0.0
                    primary = tracked_hands[0] if tracked_hands else None
                    landmarks = primary.landmarks if primary else ()
                    hand = primary.handedness if primary else None
                    if primary and primary.source_index < len(result.gestures) and result.gestures[primary.source_index]:
                        category = result.gestures[primary.source_index][0]
                        gesture = category.category_name
                        confidence = float(category.score)
                        if gesture == "None":
                            gesture = None
                    if is_pinch(landmarks):
                        gesture, confidence = "Pinch", 1.0
                    elif any(is_middle_finger(tracked.landmarks, tracked.world_landmarks)
                             for tracked in tracked_hands):
                        gesture, confidence = "Middle_Finger", 1.0
                    motion = swipe.update(landmarks, gesture, confidence, hand, timestamp)
                    height, width = rgb.shape[:2]
                    hand_points = [tracked.landmarks for tracked in tracked_hands]
                    enabled = activation.update(hand_points, width, height, timestamp)
                    if activation.changed:
                        portal_tracker.reset()
                    portal = portal_tracker.update(
                        hand_points, width, height, timestamp,
                        [tracked.world_landmarks for tracked in tracked_hands],
                    ) if enabled else None
                    rgb = render_portal(rgb, portal, timestamp)
                    for tracked in tracked_hands if self.show_landmarks else []:
                        bone_color = (255, 55, 65)
                        points = [
                            (int(point.x * width), int(point.y * height))
                            for point in tracked.landmarks
                        ]
                        for start, end in CONNECTIONS:
                            cv2.line(rgb, points[start], points[end], (15, 20, 30), 5, cv2.LINE_AA)
                            cv2.line(rgb, points[start], points[end], bone_color, 2, cv2.LINE_AA)
                        for index, point in enumerate(points):
                            fingertip = index in (4, 8, 12, 16, 20)
                            radius = 6 if fingertip else 4
                            cv2.circle(rgb, point, radius + 2, (15, 20, 30), -1, cv2.LINE_AA)
                            cv2.circle(rgb, point, radius, bone_color, -1, cv2.LINE_AA)
                    elapsed = time.monotonic() - previous_frame
                    previous_frame = time.monotonic()
                    fps = 0.85 * fps + 0.15 / max(elapsed, 1e-5)
                    qt_image = QImage(
                        rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888
                    ).copy()
                    observation = Observation(gesture, confidence, len(tracked_hands), motion)
                    with self._lock:
                        self._packet = FramePacket(qt_image, observation, fps, timestamp, portal,
                                                   enabled, activation.progress, activation.changed, backend)
        except InterruptedError:
            pass
        except Exception as error:
            if not self.isInterruptionRequested():
                logger.exception("Ошибка обработчика камеры")
                self.failed.emit(str(error))
        finally:
            if capture is not None:
                capture.release()
