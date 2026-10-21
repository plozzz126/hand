from collections import deque
from dataclasses import dataclass
from math import dist


@dataclass(frozen=True)
class Observation:
    gesture: str | None = None
    confidence: float = 0.0
    hands: int = 0
    motion: str | None = None


class GestureGate:
    def __init__(self, hold_ms=350, cooldown_ms=1000, confidence=0.65):
        self.hold_ms = hold_ms
        self.cooldown_ms = cooldown_ms
        self.confidence = confidence
        self.reset()

    def reset(self):
        self.candidate = None
        self.candidate_since = 0.0
        self.last_seen = None
        self.latched = None
        self.release_since = None
        self.last_trigger = float("-inf")
        self.progress = 0

    def update(self, observation, now):
        gesture = observation.gesture if observation.confidence >= self.confidence else None
        if self.last_seen is not None and now - self.last_seen > 0.25:
            self.candidate = None
            self.progress = 0
        self.last_seen = now
        if gesture != self.latched:
            if self.release_since is None:
                self.release_since = now
            if now - self.release_since >= 0.18:
                self.latched = None
        else:
            self.release_since = None
        if observation.motion and now - self.last_trigger >= self.cooldown_ms / 1000:
            self.last_trigger = now
            self.candidate = None
            self.progress = 0
            return observation.motion
        if gesture != self.candidate:
            self.candidate = gesture
            self.candidate_since = now
        if gesture is None:
            self.progress = 0
            return None
        duration = now - self.candidate_since
        self.progress = min(100, int(duration * 1000 / max(self.hold_ms, 1) * 100))
        if (
            duration + 1e-9 >= self.hold_ms / 1000
            and gesture != self.latched
            and now - self.last_trigger >= self.cooldown_ms / 1000
        ):
            self.last_trigger = now
            self.latched = gesture
            self.release_since = None
            return gesture
        return None


def is_pinch(landmarks):
    if len(landmarks) != 21:
        return False
    points = [(point.x, point.y, point.z) for point in landmarks]
    palm_size = dist(points[0], points[9])
    if palm_size < 1e-5:
        return False
    open_fingers = sum(
        dist(points[tip], points[0]) > dist(points[joint], points[0]) * 1.18
        for tip, joint in ((12, 10), (16, 14), (20, 18))
    )
    return dist(points[4], points[8]) / palm_size < 0.30 and open_fingers >= 2


class SwipeDetector:
    def __init__(self):
        self.history = deque()
        self.last_hand = None
        self.last_event = float("-inf")

    def update(self, landmarks, gesture, score, hand, now):
        if gesture != "Open_Palm" or score < 0.65 or not landmarks:
            self.history.clear()
            self.last_hand = None
            return None
        if hand != self.last_hand:
            self.history.clear()
        self.last_hand = hand
        if self.history and now - self.history[-1][0] > 0.20:
            self.history.clear()
        center_x = sum(landmarks[index].x for index in (0, 5, 9, 13, 17)) / 5
        center_y = sum(landmarks[index].y for index in (0, 5, 9, 13, 17)) / 5
        self.history.append((now, center_x, center_y))
        while self.history and now - self.history[0][0] > 0.45:
            self.history.popleft()
        if len(self.history) < 3 or now - self.last_event < 0.8:
            return None
        started, start_x, start_y = self.history[0]
        delta_x, delta_y = center_x - start_x, center_y - start_y
        if now - started >= 0.10 and abs(delta_x) >= 0.22 and abs(delta_y) < 0.14:
            self.last_event = now
            self.history.clear()
            return "Swipe_Right" if delta_x > 0 else "Swipe_Left"
        return None
