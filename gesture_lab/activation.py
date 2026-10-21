import math


def fingertip_contact(hands, width, height):
    if len(hands) != 2 or width <= 0 or height <= 0:
        return None
    palms = []
    tips = []
    wrists = []
    for landmarks in hands:
        if len(landmarks) != 21:
            return None
        points = {index: (landmarks[index].x * width, landmarks[index].y * height)
                  for index in (0, 4, 5, 8, 9, 17)}
        if not all(math.isfinite(coordinate) for point in points.values() for coordinate in point):
            return None
        palm = max(math.dist(points[0], points[9]), math.dist(points[5], points[17]))
        if palm < 12 or math.dist(points[4], points[8]) < palm * 0.3:
            return None
        palms.append(palm)
        wrists.append(points[0])
        tips.append((points[8], points[4]))
    scale = sum(palms) / 2
    if math.dist(wrists[0], wrists[1]) < scale * 0.6:
        return None
    distance = max(math.dist(tips[0][0], tips[1][0]), math.dist(tips[0][1], tips[1][1]))
    threshold = max(9.0, min(26.0, scale * 0.24))
    return distance / threshold


class ContactToggle:
    def __init__(self, hold_ms=120, release_ms=160):
        self.hold_seconds = hold_ms / 1000
        self.release_seconds = release_ms / 1000
        self.enabled = False
        self.latched = False
        self.touching = False
        self.changed = False
        self.progress = 0.0
        self.candidate_since = None
        self.release_since = None
        self.last_time = None

    def update(self, hands, width, height, now):
        self.changed = False
        if self.last_time is not None and (now <= self.last_time or now - self.last_time > 0.35):
            self.candidate_since = None
            self.release_since = None
        self.last_time = now
        distance = fingertip_contact(hands, width, height)
        if distance is None:
            self.touching = False
            self.candidate_since = None
            self.release_since = None
            self.progress = 0.0
            return self.enabled
        self.touching = distance <= (1.7 if self.touching or self.latched else 1.0)
        if self.touching:
            self.release_since = None
            if self.latched:
                self.progress = 1.0
                return self.enabled
            if self.candidate_since is None:
                self.candidate_since = now
            elapsed = now - self.candidate_since
            self.progress = min(1.0, elapsed / max(self.hold_seconds, 1e-6))
            if elapsed + 1e-9 >= self.hold_seconds:
                self.enabled = not self.enabled
                self.latched = True
                self.changed = True
                self.progress = 1.0
        else:
            self.candidate_since = None
            self.progress = 0.0
            if self.release_since is None:
                self.release_since = now
            if now - self.release_since + 1e-9 >= self.release_seconds:
                self.latched = False
        return self.enabled
