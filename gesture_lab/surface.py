import math

SURFACE_TRIANGLES = ((0, 4, 3), (3, 4, 5), (4, 1, 5), (5, 1, 2))
SURFACE_UV = ((0, 0), (1, 0), (1, 1), (0, 1), (0.5, 0), (0.5, 1))
SURFACE_OUTLINE = (0, 4, 1, 2, 5, 3)


def surface_vertices(corners, fold, width, height):
    points = [(point[0] * width, point[1] * height) for point in corners]
    left_center = tuple((points[0][axis] + points[3][axis]) / 2 for axis in range(2))
    right_center = tuple((points[1][axis] + points[2][axis]) / 2 for axis in range(2))
    span = math.dist(left_center, right_center)
    perpendicular = (-(right_center[1] - left_center[1]) / max(span, 1e-6),
                     (right_center[0] - left_center[0]) / max(span, 1e-6))
    grip_size = (math.dist(points[0], points[3]) + math.dist(points[1], points[2])) / 2
    displacement = math.sin(fold) * min(span * 0.24, grip_size * 0.76)
    center = tuple((left_center[axis] + right_center[axis]) / 2
                   + perpendicular[axis] * displacement for axis in range(2))
    cross_section = tuple(((points[3][axis] - points[0][axis])
                           + (points[2][axis] - points[1][axis])) / 2 for axis in range(2))
    top = tuple((center[axis] - cross_section[axis] / 2) / (width if axis == 0 else height)
                for axis in range(2))
    bottom = tuple((center[axis] + cross_section[axis] / 2) / (width if axis == 0 else height)
                   for axis in range(2))
    return (*corners, top, bottom)


def surface_coordinates(vertices, columns, rows):
    import numpy as np

    horizontal = np.zeros_like(columns)
    vertical = np.zeros_like(rows)
    inside = np.zeros(columns.shape, dtype=bool)
    for triangle in SURFACE_TRIANGLES:
        first, second, third = vertices[list(triangle)]
        denominator = ((second[1] - third[1]) * (first[0] - third[0])
                       + (third[0] - second[0]) * (first[1] - third[1]))
        if abs(denominator) < 0.5:
            continue
        weight_first = ((second[1] - third[1]) * (columns - third[0])
                        + (third[0] - second[0]) * (rows - third[1])) / denominator
        weight_second = ((third[1] - first[1]) * (columns - third[0])
                         + (first[0] - third[0]) * (rows - third[1])) / denominator
        weight_third = 1 - weight_first - weight_second
        mask = (weight_first >= -1e-5) & (weight_second >= -1e-5) & (weight_third >= -1e-5)
        texture = np.asarray([SURFACE_UV[index] for index in triangle], dtype=np.float32)
        horizontal[mask] = (weight_first * texture[0, 0] + weight_second * texture[1, 0]
                            + weight_third * texture[2, 0])[mask]
        vertical[mask] = (weight_first * texture[0, 1] + weight_second * texture[1, 1]
                          + weight_third * texture[2, 1])[mask]
        inside |= mask
    return horizontal, vertical, inside


def surface_projection(vertices, horizontal, vertical):
    import cv2
    import numpy as np

    map_x = np.zeros_like(horizontal)
    map_y = np.zeros_like(vertical)
    left = horizontal <= 0.5
    first_half = np.where(left, horizontal * 2 + vertical <= 1,
                         (horizontal - 0.5) * 2 + vertical <= 1)
    masks = (left & first_half, left & ~first_half, ~left & first_half, ~left & ~first_half)
    for triangle, mask in zip(SURFACE_TRIANGLES, masks, strict=True):
        texture = np.asarray([SURFACE_UV[index] for index in triangle], dtype=np.float32)
        transform = cv2.getAffineTransform(texture, vertices[list(triangle)]).astype(np.float32)
        map_x[mask] = (transform[0, 0] * horizontal + transform[0, 1] * vertical + transform[0, 2])[mask]
        map_y[mask] = (transform[1, 0] * horizontal + transform[1, 1] * vertical + transform[1, 2])[mask]
    return map_x, map_y
