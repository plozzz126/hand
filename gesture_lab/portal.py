import math
from dataclasses import dataclass

from gesture_lab.surface import (
    SURFACE_OUTLINE,
    SURFACE_TRIANGLES,
    surface_coordinates,
    surface_projection,
    surface_vertices,
)


@dataclass(frozen=True)
class PortalState:
    corners: tuple[tuple[float, float], ...]
    opacity: float
    opening: float
    stretch: float | None = None
    twist: float = 0.0
    fold: float = 0.0


PORTAL_FILTERS = (
    ("lens", "Линза"),
    ("mono", "Чёрно-белое"),
    ("waves", "Жидкие волны"),
    ("glitch", "Пиксельный глитч"),
    ("thermal", "Термовизор"),
    ("kaleido", "Калейдоскоп"),
    ("vortex", "Вихрь"),
)


def portal_stretch(state):
    value = state.opening if state.stretch is None else state.stretch
    return min(1.0, max(0.0, value))


def portal_weights(state):
    position = portal_stretch(state) * len(PORTAL_FILTERS)
    index = min(len(PORTAL_FILTERS) - 1, int(position))
    if index == len(PORTAL_FILTERS) - 1:
        return ((index, 1.0),)
    blend = min(1.0, max(0.0, (position - index - 0.72) / 0.28))
    blend = blend * blend * (3 - 2 * blend)
    return ((index, 1 - blend), (index + 1, blend)) if blend > 0 else ((index, 1.0),)


def portal_description(state):
    index, _ = max(portal_weights(state), key=lambda item: item[1])
    rotation = " · ↻" if state.twist > 0.15 else " · ↺" if state.twist < -0.15 else ""
    bend = " · сгиб" if abs(state.fold) > 0.08 else ""
    return f"{PORTAL_FILTERS[index][1]} · {portal_stretch(state):.0%}{rotation}{bend}"


def portal_target(hands, width, height, world_hands=(), reference_corners=None):
    if len(hands) != 2 or width <= 0 or height <= 0:
        return None
    grips = []
    for hand_index, landmarks in enumerate(hands):
        if len(landmarks) != 21:
            return None
        points = [(point.x * width, point.y * height, point.z * width) for point in landmarks]
        if not all(math.isfinite(value) for point in points for value in point):
            return None
        palm = math.dist(points[0], points[9])
        if palm < 12:
            return None
        opening = math.dist(points[4], points[8]) / palm
        if (
            opening < 0.38
            or math.dist(points[8], points[0]) < palm * 1.05
            or math.dist(points[4], points[0]) < palm * 0.65
        ):
            return None
        tips = tuple((landmarks[index].x, landmarks[index].y) for index in (8, 4))
        if math.dist(points[4][:2], points[8][:2]) < 16:
            return None
        roll = math.atan2((tips[1][0] - tips[0][0]) * width,
                          (tips[1][1] - tips[0][1]) * height)
        orientation = points
        world = world_hands[hand_index] if hand_index < len(world_hands) else ()
        if len(world) == 21:
            candidate = [(point.x, point.y, point.z) for point in world]
            if all(math.isfinite(value) for point in candidate for value in point):
                orientation = candidate
        depth_tilt = math.atan2(orientation[4][2] - orientation[8][2],
                                max(math.dist(orientation[4][:2], orientation[8][:2]), 1e-6))
        grips.append((sum(point[0] for point in tips) / 2, tips, opening,
                      landmarks[0].x, palm, roll, depth_tilt, points[0][:2]))
    grips.sort(key=lambda grip: grip[3])
    if reference_corners:
        previous = (reference_corners[0], reference_corners[1], reference_corners[2], reference_corners[3])
        current = (grips[0][1][0], grips[1][1][0], grips[1][1][1], grips[0][1][1])
        swapped = (current[1], current[0], current[3], current[2])
        direct_cost = sum(math.dist(old, new) for old, new in zip(previous, current, strict=True))
        swapped_cost = sum(math.dist(old, new) for old, new in zip(previous, swapped, strict=True))
        if swapped_cost < direct_cost:
            grips.reverse()
    left, right = grips
    corners = (left[1][0], right[1][0], right[1][1], left[1][1])
    if any(not -0.08 <= coordinate <= 1.08 for point in corners for coordinate in point):
        return None
    opening = min(1.0, max(0.0, (min(left[2], right[2]) - 0.38) / 1.2))
    left_center = (left[0] * width, sum(point[1] for point in left[1]) * height / 2)
    right_center = (right[0] * width, sum(point[1] for point in right[1]) * height / 2)
    if math.dist(left_center, right_center) < 55 or math.dist(left[7], right[7]) < 55:
        return None
    relative_span = math.dist(left_center, right_center) / ((left[4] + right[4]) / 2)
    horizontal_stretch = min(1.0, max(0.0, (relative_span - 0.65) / 3.3))
    stretch = min(1.0, horizontal_stretch * 0.72 + opening * 0.28)
    tilt = math.atan2(right_center[1] - left_center[1], right_center[0] - left_center[0])
    twist = tilt * 3 + (right[5] + left[5]) * 0.5
    twist = math.copysign(max(0.0, abs(twist) - 0.08), twist)
    roll_difference = right[5] - left[5]
    fold = math.sin(roll_difference) * 0.95 + (right[6] - left[6]) * 0.65
    fold = math.copysign(min(1.25, max(0.0, abs(fold) - 0.16)), fold)
    vertices = surface_vertices(corners, fold, width, height)
    area = 0.0
    for triangle in SURFACE_TRIANGLES:
        first, second, third = (vertices[index] for index in triangle)
        area += abs((second[0] - first[0]) * (third[1] - first[1])
                    - (third[0] - first[0]) * (second[1] - first[1])) / 2
    if area * width * height < 1200:
        return None
    return PortalState(corners, 1.0, opening, stretch, twist, fold)


class PortalTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.state = None
        self.last_time = None
        self.last_detected = float("-inf")

    def update(self, hands, width, height, now, world_hands=()):
        reference = self.state.corners if self.state and self.last_time is not None and now - self.last_time < 0.25 else None
        target = portal_target(hands, width, height, world_hands, reference)
        elapsed = 1 / 30 if self.last_time is None else max(0.0, now - self.last_time)
        self.last_time = now
        if elapsed > 0.5:
            self.state = None
        if target:
            self.last_detected = now
            if self.state is None:
                self.state = PortalState(target.corners, 0.18, target.opening, target.stretch, target.twist, target.fold)
            else:
                speed = max(math.dist(old, new) for old, new in zip(self.state.corners, target.corners, strict=True)) / max(elapsed, 1e-3)
                response = max(0.018, 0.065 / (1 + speed * 3))
                blend = 1 - math.exp(-elapsed / response)
                corners = tuple(tuple(previous + (current - previous) * blend
                                      for previous, current in zip(old, new, strict=True))
                                for old, new in zip(self.state.corners, target.corners, strict=True))
                self.state = PortalState(
                    corners,
                    min(1.0, self.state.opacity + elapsed * 5),
                    self.state.opening + (target.opening - self.state.opening) * blend,
                    portal_stretch(self.state) + (target.stretch - portal_stretch(self.state)) * blend,
                    self.state.twist + math.atan2(math.sin(target.twist - self.state.twist),
                                                 math.cos(target.twist - self.state.twist)) * blend,
                    self.state.fold + (target.fold - self.state.fold) * blend,
                )
        elif self.state and now - self.last_detected > 0.12:
            opacity = self.state.opacity - elapsed * 5
            self.state = PortalState(self.state.corners, opacity, self.state.opening,
                                     self.state.stretch, self.state.twist, self.state.fold) if opacity > 0 else None
        return self.state


def filter_coordinates(name, horizontal, vertical, envelope, strength, clock):
    import numpy as np

    center_x, center_y = horizontal - 0.5, vertical - 0.5
    radius_squared = center_x * center_x + center_y * center_y
    if name == "lens":
        factor = 1 - envelope * (0.18 + strength * 0.2)
        return 0.5 + center_x * factor, 0.5 + center_y * factor
    if name == "mono":
        factor = 1 - envelope * 0.4 * strength
        return 0.5 + center_x * factor, 0.5 + center_y * factor
    if name == "waves":
        return (horizontal + np.sin(vertical * 22 - clock * 2.8) * 0.075 * strength * envelope,
                vertical + np.sin(horizontal * 18 + clock * 2.1) * 0.065 * strength * envelope)
    if name == "glitch":
        cells = 26 - strength * 16
        pixel_x = (np.floor(horizontal * cells) + 0.5) / cells
        pixel_y = (np.floor(vertical * cells) + 0.5) / cells
        bands = np.sin(np.floor(vertical * 24) * 13 + math.floor(clock * 7))
        shift = np.where(bands > 0.75, np.sin(clock * 3) * 0.12, 0)
        edge = np.minimum(envelope * 7, 1)
        return horizontal + (pixel_x - horizontal + shift) * edge, vertical + (pixel_y - vertical) * edge
    if name == "thermal":
        return horizontal + np.sin(vertical * 9 + clock) * 0.025 * envelope, vertical
    if name == "kaleido":
        radius = np.sqrt(radius_squared)
        sector = math.tau / 6
        angle = np.arctan2(center_y, center_x) + clock * 0.16
        folded = np.abs((angle + sector / 2) % sector - sector / 2)
        return (horizontal + (0.5 + radius * np.cos(folded) - horizontal) * envelope,
                vertical + (0.5 + radius * np.sin(folded) - vertical) * envelope)
    angle = (3.6 + math.sin(clock * 0.8) * 0.6) * strength * envelope
    cosine, sine = np.cos(angle), np.sin(angle)
    return 0.5 + center_x * cosine - center_y * sine, 0.5 + center_x * sine + center_y * cosine


def render_portal(rgb, state, now, *, grid_step=None):
    if state is None or state.opacity <= 0:
        return rgb
    import cv2
    import numpy as np

    height, width = rgb.shape[:2]
    vertices = np.asarray(surface_vertices(state.corners, state.fold, width, height), dtype=np.float32)
    vertices *= np.array([width, height], dtype=np.float32)
    left = max(0, int(np.floor(vertices[:, 0].min())) - 14)
    top = max(0, int(np.floor(vertices[:, 1].min())) - 14)
    right = min(width, int(np.ceil(vertices[:, 0].max())) + 15)
    bottom = min(height, int(np.ceil(vertices[:, 1].max())) + 15)
    if right - left < 4 or bottom - top < 4:
        return rgb
    patch = rgb[top:bottom, left:right]
    patch_height, patch_width = patch.shape[:2]
    if grid_step is None:
        grid_step = max(4, math.ceil(math.sqrt(patch_width * patch_height / 16384)))
    local_vertices = vertices - np.array([left, top], dtype=np.float32)
    grid_width = max(2, math.ceil(patch_width / grid_step))
    grid_height = max(2, math.ceil(patch_height / grid_step))
    columns, rows = np.meshgrid(
        (np.arange(grid_width, dtype=np.float32) + 0.5) * (patch_width / grid_width) - 0.5,
        (np.arange(grid_height, dtype=np.float32) + 0.5) * (patch_height / grid_height) - 0.5,
    )
    horizontal, vertical, inside = surface_coordinates(local_vertices, columns, rows)
    envelope = np.sin(np.clip(horizontal, 0, 1) * math.pi) * np.sin(np.clip(vertical, 0, 1) * math.pi)
    strength = 0.35 + state.opening * 0.65
    clock = now % 1000
    rotation = state.twist * 2.5 * envelope
    cosine, sine = np.cos(rotation), np.sin(rotation)
    center_x, center_y = horizontal - 0.5, vertical - 0.5
    twisted_x = 0.5 + center_x * cosine - center_y * sine
    twisted_y = 0.5 + center_x * sine + center_y * cosine
    profiles = portal_weights(state)
    sample_x = np.zeros_like(horizontal)
    sample_y = np.zeros_like(vertical)
    for index, weight in profiles:
        mapped_x, mapped_y = filter_coordinates(PORTAL_FILTERS[index][0], twisted_x, twisted_y,
                                               envelope, strength, clock)
        sample_x += mapped_x * weight
        sample_y += mapped_y * weight
    map_x, map_y = surface_projection(vertices, sample_x, sample_y)
    def expand(field):
        return cv2.resize(field, (patch_width, patch_height), interpolation=cv2.INTER_LINEAR)

    map_x, map_y = expand(map_x), expand(map_y)
    warped = cv2.remap(rgb, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    monochrome = sum(weight for index, weight in profiles if PORTAL_FILTERS[index][0] == "mono")
    glitch = sum(weight for index, weight in profiles if PORTAL_FILTERS[index][0] == "glitch")
    thermal = sum(weight for index, weight in profiles if PORTAL_FILTERS[index][0] == "thermal")
    if monochrome < 1:
        aberration = expand(envelope * strength * (3 + glitch * 8) * (1 - monochrome))
        warped[:, :, 0] = cv2.remap(rgb[:, :, 0], map_x + aberration, map_y,
                                  cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
        warped[:, :, 2] = cv2.remap(rgb[:, :, 2], map_x - aberration, map_y,
                                  cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    grayscale = cv2.cvtColor(warped, cv2.COLOR_RGB2GRAY) if monochrome > 0 or thermal > 0 else None
    if monochrome > 0:
        film_curve = np.clip(np.arange(256, dtype=np.float32) * 1.25 - 32, 0, 255).astype(np.uint8)
        film = cv2.LUT(grayscale, film_curve)
        warped = cv2.addWeighted(warped, 1 - monochrome,
                                 cv2.cvtColor(film, cv2.COLOR_GRAY2RGB), monochrome, 0)
    if thermal > 0:
        heat = cv2.cvtColor(cv2.applyColorMap(grayscale, cv2.COLORMAP_TURBO), cv2.COLOR_BGR2RGB)
        warped = cv2.addWeighted(warped, 1 - thermal, heat, thermal, 0)
    scan = (np.sin(vertical * 95 - clock * 4) * 0.5 + 0.5) * 3 * envelope
    bend = math.sin(state.fold)
    shading = 1 + bend * 0.12 * np.tanh((horizontal - 0.5) * 12)
    shading -= abs(bend) * 0.12 * np.exp(-((horizontal - 0.5) / 0.018) ** 2)
    if glitch > 0:
        shading *= 1 - (np.floor(vertical * 65) % 2) * glitch * 0.16
    alpha = expand((inside * np.minimum(envelope * 18, 1) * state.opacity).astype(np.float32))
    gain = cv2.cvtColor(expand(shading), cv2.COLOR_GRAY2RGB)
    foreground = cv2.multiply(warped, gain, dtype=cv2.CV_8U)
    illumination = expand(scan * shading).astype(np.uint8)
    foreground = cv2.add(foreground, cv2.cvtColor(illumination, cv2.COLOR_GRAY2RGB))
    composed = cv2.blendLinear(patch, foreground, 1 - alpha, alpha)
    border = np.zeros_like(patch)
    pixel_vertices = np.rint(local_vertices).astype(np.int32)
    polygon = pixel_vertices[list(SURFACE_OUTLINE)]
    cv2.polylines(border, [polygon], True, (75, 235, 255), 2, cv2.LINE_AA)
    for corner in pixel_vertices[:4]:
        cv2.circle(border, tuple(corner), 5, (210, 255, 255), 1, cv2.LINE_AA)
    crease = np.zeros_like(border)
    cv2.line(crease, tuple(pixel_vertices[4]), tuple(pixel_vertices[5]), (210, 210, 210), 1, cv2.LINE_AA)
    border = cv2.addWeighted(border, 1.0, crease, min(1.0, abs(bend) * 0.8), 0)
    glow = cv2.resize(border, (max(2, patch_width // 2), max(2, patch_height // 2)),
                      interpolation=cv2.INTER_AREA)
    glow = cv2.GaussianBlur(glow, (0, 0), 2.5)
    glow = cv2.resize(glow, (patch_width, patch_height), interpolation=cv2.INTER_LINEAR)
    composed = cv2.addWeighted(composed, 1.0, glow, state.opacity * 0.75, 0)
    composed = cv2.addWeighted(composed, 1.0, border, state.opacity * 0.8, 0)
    result = rgb.copy()
    result[top:bottom, left:right] = composed
    return result
