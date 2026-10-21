import math
import unittest
from types import SimpleNamespace

import numpy as np
from test_portal import two_hands

from gesture_lab.portal import PortalTracker, portal_target, render_portal
from gesture_lab.surface import (
    surface_coordinates,
    surface_projection,
    surface_vertices,
)


def turn_right_hand(degrees):
    hands = two_hands()
    center_x = (hands[1][8].x + hands[1][4].x) * 640 / 2
    center_y = (hands[1][8].y + hands[1][4].y) * 480 / 2
    angle = math.radians(degrees)
    for point in hands[1]:
        horizontal, vertical = point.x * 640 - center_x, point.y * 480 - center_y
        point.x = (center_x + horizontal * math.cos(angle) - vertical * math.sin(angle)) / 640
        point.y = (center_y + horizontal * math.sin(angle) + vertical * math.cos(angle)) / 480
    return hands


class FoldingSurfaceTests(unittest.TestCase):
    def test_local_world_depth_changes_fold_without_using_global_hand_origins(self):
        hands = two_hands()
        world = [[SimpleNamespace(x=point.x * 0.1, y=point.y * 0.1, z=point.z * 0.1)
                  for point in landmarks] for landmarks in hands]
        flat = portal_target(hands, 640, 480, world)
        world[1][4].z -= 0.02
        bent = portal_target(hands, 640, 480, world)
        self.assertGreater(abs(bent.fold - flat.fold), 0.1)
        for hand_index, landmarks in enumerate(world):
            for point in landmarks:
                point.x += 10 + hand_index
                point.y -= 20 + hand_index
                point.z += 30 + hand_index
        translated = portal_target(hands, 640, 480, world)
        self.assertAlmostEqual(translated.fold, bent.fold, places=8)

    def test_surface_edges_stay_attached_to_anatomical_fingertips(self):
        for degrees in (0, 30, 60, 90, 120, 150):
            with self.subTest(rotation=degrees):
                hands = turn_right_hand(degrees)
                state = portal_target(hands, 640, 480)
                self.assertIsNotNone(state)
                self.assertEqual(state.corners[1], (hands[1][8].x, hands[1][8].y))
                self.assertEqual(state.corners[2], (hands[1][4].x, hands[1][4].y))
                vertices = surface_vertices(state.corners, state.fold, 640, 480)
                self.assertEqual(vertices[:4], state.corners)

    def test_center_crease_moves_continuously_as_wrist_rotates(self):
        previous = None
        for degrees in range(0, 121, 2):
            state = portal_target(turn_right_hand(degrees), 640, 480)
            self.assertIsNotNone(state)
            vertices = surface_vertices(state.corners, state.fold, 640, 480)
            if previous:
                self.assertLess(math.dist(vertices[4], previous[4]), 0.025)
                self.assertLess(math.dist(vertices[5], previous[5]), 0.025)
            previous = vertices

    def test_rotating_one_grip_produces_a_real_extra_corner(self):
        state = portal_target(turn_right_hand(70), 640, 480)
        vertices = surface_vertices(state.corners, state.fold, 640, 480)
        straight_top = tuple((state.corners[0][axis] + state.corners[1][axis]) / 2 for axis in range(2))
        self.assertGreater(math.dist(vertices[4], straight_top), 0.05)

    def test_flat_surface_has_no_preset_bend(self):
        state = portal_target(two_hands(), 640, 480)
        self.assertAlmostEqual(state.fold, 0)
        vertices = surface_vertices(state.corners, state.fold, 640, 480)
        self.assertAlmostEqual(vertices[4][0], (state.corners[0][0] + state.corners[1][0]) / 2)
        self.assertAlmostEqual(vertices[4][1], (state.corners[0][1] + state.corners[1][1]) / 2)

    def test_tracker_does_not_exchange_index_and_thumb_at_ninety_degrees(self):
        tracker = PortalTracker()
        previous = None
        for frame, degrees in enumerate(range(60, 121, 2)):
            state = tracker.update(turn_right_hand(degrees), 640, 480, frame / 30)
            self.assertIsNotNone(state)
            if previous:
                self.assertLess(math.dist(state.corners[1], previous.corners[1]), 0.03)
                self.assertLess(math.dist(state.corners[2], previous.corners[2]), 0.03)
            previous = state

    def test_inverse_mesh_mapping_is_continuous_across_the_crease(self):
        state = portal_target(turn_right_hand(65), 640, 480)
        vertices = np.asarray(surface_vertices(state.corners, state.fold, 640, 480), dtype=np.float32)
        vertices *= np.array([640, 480], dtype=np.float32)
        horizontal = np.array([[0.2, 0.4999, 0.5, 0.5001, 0.8]], dtype=np.float32)
        vertical = np.full_like(horizontal, 0.4)
        columns, rows = surface_projection(vertices, horizontal, vertical)
        restored_x, restored_y, inside = surface_coordinates(vertices, columns, rows)
        self.assertTrue(inside.all())
        np.testing.assert_allclose(restored_x, horizontal, atol=1e-5)
        np.testing.assert_allclose(restored_y, vertical, atol=1e-5)

    def test_rendering_survives_strong_rotation_without_distorting_whole_frame(self):
        rows, columns = np.mgrid[:480, :640]
        channel = (((rows // 20 + columns // 20) % 2) * 170 + 40).astype(np.uint8)
        frame = np.stack((channel, channel, channel), axis=-1)
        for degrees in (60, 90, 120):
            state = portal_target(turn_right_hand(degrees), 640, 480)
            result = render_portal(frame, state, 1)
            self.assertEqual(result.shape, frame.shape)
            self.assertTrue(np.isfinite(result).all())
            np.testing.assert_array_equal(result[:, :80], frame[:, :80])


if __name__ == "__main__":
    unittest.main()
