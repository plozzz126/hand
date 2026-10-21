import math
from dataclasses import dataclass
from itertools import product

import numpy as np


@dataclass(frozen=True)
class Joint:
    x: float
    y: float
    z: float


class OneEuroFilter:
    def __init__(self, min_cutoff=2.0, beta=16.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.value = None
        self.raw = None
        self.derivative = None
        self.timestamp = None

    def update(self, values, now):
        values = np.asarray(values, dtype=np.float32)
        if self.value is None or now - self.timestamp > 0.25:
            self.value = values.copy()
            self.raw = values.copy()
            self.derivative = np.zeros_like(values)
            self.timestamp = now
            return self.value.copy()
        elapsed = now - self.timestamp
        if elapsed <= 0:
            return self.value.copy()
        derivative_blend = 1 / (1 + 1 / (math.tau * elapsed))
        derivative = (values - self.raw) / elapsed
        self.derivative += (derivative - self.derivative) * derivative_blend
        speed = np.linalg.norm(self.derivative, axis=-1, keepdims=True)
        cutoff = self.min_cutoff + self.beta * speed
        blend = 1 / (1 + 1 / (math.tau * cutoff * elapsed))
        self.value += (values - self.value) * blend
        self.raw = values.copy()
        self.timestamp = now
        return self.value.copy()


@dataclass(frozen=True)
class TrackedHand:
    track_id: int
    landmarks: tuple[Joint, ...]
    world_landmarks: tuple[Joint, ...]
    handedness: str | None
    source_index: int


class HandTracker:
    def __init__(self):
        self.tracks = {}
        self.next_id = 0

    def update(self, hands, handedness, world_hands, now):
        self.tracks = {key: value for key, value in self.tracks.items()
                       if 0 <= now - value["timestamp"] <= 0.25}
        detections = []
        for source_index, landmarks in enumerate(hands[:2]):
            if len(landmarks) != 21:
                continue
            points = np.asarray([(point.x, point.y, point.z) for point in landmarks], dtype=np.float32)
            if not np.isfinite(points).all():
                continue
            scale = max(float(np.linalg.norm(points[0, :2] - points[9, :2])),
                        float(np.linalg.norm(points[5, :2] - points[17, :2])), 0.025)
            center = points[[0, 5, 9, 13, 17], :2].mean(axis=0)
            categories = handedness[source_index] if source_index < len(handedness) else []
            side = categories[0].category_name if categories else None
            score = float(categories[0].score) if categories else 0.0
            detections.append((source_index, points, center, scale, side, score))
        identities = list(self.tracks)

        def cost(detection, track_id):
            if track_id is None:
                return 2.6
            _, _, center, scale, side, score = detection
            track = self.tracks[track_id]
            elapsed = now - track["timestamp"]
            prediction = track["center"] + np.clip(track["velocity"] * min(elapsed, 0.1), -0.08, 0.08)
            distance = float(np.linalg.norm(center - prediction)) / max(scale, track["scale"])
            if distance > 2.5:
                return 100.0
            mismatch = 0.9 * score if side and track["side"] and side != track["side"] else 0.0
            return distance + mismatch

        assignments = product([*identities, None], repeat=len(detections))
        valid_assignments = (assignment for assignment in assignments
                             if len([key for key in assignment if key is not None])
                             == len({key for key in assignment if key is not None}))
        selected = min(valid_assignments,
                       key=lambda assignment: sum(cost(detection, key)
                                                  for detection, key in zip(detections, assignment, strict=True)))
        tracked = []
        for detection, track_id in zip(detections, selected, strict=True):
            source_index, points, center, scale, side, score = detection
            if track_id is None:
                track_id = self.next_id
                self.next_id += 1
                self.tracks[track_id] = {
                    "filter": OneEuroFilter(), "world_filter": OneEuroFilter(),
                    "center": center, "velocity": np.zeros(2, dtype=np.float32),
                    "scale": scale, "side": side if score >= 0.7 else None, "timestamp": now,
                }
            track = self.tracks[track_id]
            elapsed = now - track["timestamp"]
            if elapsed > 0:
                velocity = (center - track["center"]) / elapsed
                track["velocity"] = track["velocity"] * 0.65 + velocity * 0.35
            if track["side"] is None and score >= 0.7:
                track["side"] = side
            filtered = track["filter"].update(points, now)
            track.update(center=center, scale=scale, timestamp=now)
            world = world_hands[source_index] if source_index < len(world_hands) else []
            filtered_world = ()
            if len(world) == 21:
                world_points = np.asarray([(point.x, point.y, point.z) for point in world], dtype=np.float32)
                if np.isfinite(world_points).all():
                    filtered_world = tuple(Joint(*map(float, point))
                                           for point in track["world_filter"].update(world_points, now))
            tracked.append(TrackedHand(track_id, tuple(Joint(*map(float, point)) for point in filtered),
                                       filtered_world, track["side"], source_index))
        return sorted(tracked, key=lambda hand: hand.track_id)
