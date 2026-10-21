import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from gesture_lab.portal import (
    PORTAL_FILTERS,
    PortalState,
    PortalTracker,
    portal_description,
    portal_target,
    portal_weights,
    render_portal,
)
from gesture_lab.surface import surface_coordinates


def grip(horizontal, mirrored=False, opening=0.35):
    direction = -1 if mirrored else 1
    points = [SimpleNamespace(x=horizontal, y=0.7, z=0.0) for _ in range(21)]
    points[0].y = 0.85
    points[9].y = 0.60
    points[8].x = horizontal + 0.08 * direction
    points[8].y = 0.64 - opening
    points[4].x = horizontal + 0.10 * direction
    points[4].y = 0.64
    return points


def two_hands():
    return [grip(0.22), grip(0.78, mirrored=True)]


class PortalGeometryTests(unittest.TestCase):
    def test_two_open_grips_make_a_screen_between_four_fingertips(self):
        state = portal_target(two_hands(), 640, 480)
        self.assertIsNotNone(state)
        self.assertAlmostEqual(state.corners[0][0], 0.30)
        self.assertAlmostEqual(state.corners[1][0], 0.70)
        self.assertAlmostEqual(state.corners[2][1], 0.64)
        self.assertAlmostEqual(state.corners[3][1], 0.64)

    def test_detection_order_does_not_flip_the_screen(self):
        hands = two_hands()
        self.assertEqual(portal_target(hands, 640, 480), portal_target(hands[::-1], 640, 480))

    def test_single_hand_or_closed_grip_does_not_open_screen(self):
        self.assertIsNone(portal_target(two_hands()[:1], 640, 480))
        self.assertIsNone(portal_target([grip(0.22, opening=0.01), grip(0.78, True)], 640, 480))

    def test_bringing_hands_together_closes_screen(self):
        self.assertIsNone(portal_target([grip(0.47), grip(0.53, True)], 640, 480))

    def test_wider_finger_gap_increases_screen_height(self):
        small = portal_target([grip(0.22, opening=0.2), grip(0.78, True, opening=0.2)], 640, 480)
        large = portal_target(two_hands(), 640, 480)
        self.assertIsNotNone(small)
        self.assertGreater(large.corners[3][1] - large.corners[0][1],
                           small.corners[3][1] - small.corners[0][1])
        self.assertGreater(large.opening, small.opening)

    def test_invalid_landmarks_are_rejected(self):
        hands = two_hands()
        hands[0][8].x = float("nan")
        self.assertIsNone(portal_target(hands, 640, 480))
        self.assertIsNone(portal_target([[], []], 640, 480))

    def test_tracking_smooths_motion_and_fades_after_release(self):
        tracker = PortalTracker()
        for frame in range(12):
            state = tracker.update(two_hands(), 640, 480, frame / 30)
        self.assertAlmostEqual(state.opacity, 1)
        moved = [grip(0.12), grip(0.88, True)]
        smoothed = tracker.update(moved, 640, 480, 0.4)
        target = portal_target(moved, 640, 480)
        self.assertGreater(smoothed.corners[0][0], target.corners[0][0])
        self.assertLess(smoothed.corners[0][0], state.corners[0][0])
        self.assertIsNotNone(tracker.update([], 640, 480, 0.45))
        faded = tracker.update([], 640, 480, 0.6)
        self.assertLess(faded.opacity, 1)
        self.assertIsNone(tracker.update([], 640, 480, 0.9))

    def test_camera_stall_does_not_leave_frozen_glass(self):
        tracker = PortalTracker()
        tracker.update(two_hands(), 640, 480, 0)
        self.assertIsNone(tracker.update([], 640, 480, 2))

    def test_distance_between_hands_changes_filter_stretch(self):
        narrow = portal_target([grip(0.32), grip(0.68, True)], 640, 480)
        wide = portal_target([grip(0.10), grip(0.90, True)], 640, 480)
        self.assertIsNotNone(narrow)
        self.assertGreater(wide.stretch, narrow.stretch)
        self.assertNotEqual(portal_weights(wide)[0][0], portal_weights(narrow)[0][0])

    def test_level_grips_are_neutral_and_tilt_controls_both_spin_directions(self):
        neutral = portal_target(two_hands(), 640, 480)
        self.assertAlmostEqual(neutral.twist, 0)
        twists = []
        for offset in (-0.15, 0.15):
            hands = two_hands()
            for point in hands[1]:
                point.y += offset
            state = portal_target(hands, 640, 480)
            self.assertIsNotNone(state)
            twists.append(state.twist)
        self.assertLess(twists[0], -0.2)
        self.assertGreater(twists[1], 0.2)

    def test_tracker_smooths_stretch_and_twist_and_preserves_them_on_release(self):
        tracker = PortalTracker()
        for frame in range(10):
            before = tracker.update(two_hands(), 640, 480, frame * 0.03)
        hands = [grip(0.10), grip(0.90, True)]
        for point in hands[1]:
            point.y += 0.12
        target = portal_target(hands, 640, 480)
        smoothed = tracker.update(hands, 640, 480, 0.30)
        self.assertGreater(smoothed.stretch, before.stretch)
        self.assertLess(smoothed.stretch, target.stretch)
        self.assertGreater(smoothed.twist, before.twist)
        self.assertLess(smoothed.twist, target.twist)
        fading = tracker.update([], 640, 480, 0.45)
        self.assertIsNotNone(fading)
        self.assertEqual(fading.stretch, smoothed.stretch)
        self.assertEqual(fading.twist, smoothed.twist)


class PortalFilterSelectionTests(unittest.TestCase):
    def test_every_filter_has_a_stable_range_without_mixing(self):
        for index, details in enumerate(PORTAL_FILTERS):
            with self.subTest(filter=details[0]):
                state = PortalState((), 1, 1, stretch=(index + 0.35) / len(PORTAL_FILTERS))
                self.assertEqual(portal_weights(state), ((index, 1.0),))
                self.assertIn(details[1], portal_description(state))

    def test_filters_crossfade_at_boundary_without_skipping(self):
        count = len(PORTAL_FILTERS)
        state = PortalState((), 1, 1, stretch=1.85 / count)
        weights = portal_weights(state)
        self.assertEqual([index for index, _ in weights], [1, 2])
        self.assertAlmostEqual(sum(weight for _, weight in weights), 1)
        self.assertTrue(all(0 < weight < 1 for _, weight in weights))

    def test_full_stretch_selects_vortex_and_limits_are_clamped(self):
        self.assertEqual(portal_weights(PortalState((), 1, 1, stretch=5)), ((6, 1.0),))
        self.assertEqual(portal_weights(PortalState((), 1, 1, stretch=-1)), ((0, 1.0),))


class PortalRenderingTests(unittest.TestCase):
    def setUp(self):
        rows, columns = np.mgrid[:480, :640]
        grid = (((rows // 16 + columns // 16) % 2) * 180 + 30).astype(np.uint8)
        self.frame = np.stack((grid, grid, grid), axis=-1)
        self.state = portal_target(two_hands(), 640, 480)

    def test_glass_distorts_camera_pixels_and_preserves_outside(self):
        original = self.frame.copy()
        rendered = render_portal(self.frame, self.state, 1)
        self.assertEqual(rendered.shape, self.frame.shape)
        self.assertEqual(rendered.dtype, np.uint8)
        self.assertFalse(np.array_equal(rendered[150:300, 220:420], self.frame[150:300, 220:420]))
        np.testing.assert_array_equal(rendered[:80], self.frame[:80])
        np.testing.assert_array_equal(rendered[:, :100], self.frame[:, :100])
        np.testing.assert_array_equal(self.frame, original)

    def test_sparse_warp_grid_does_not_reduce_camera_resolution(self):
        with patch("gesture_lab.portal.surface_coordinates", wraps=surface_coordinates) as coordinates:
            rendered = render_portal(self.frame, self.state, 1)
        columns, rows = coordinates.call_args.args[1:]
        self.assertLess(columns.shape[1], self.frame.shape[1] // 4)
        self.assertLess(rows.shape[0], self.frame.shape[0] // 4)
        self.assertEqual(rendered.shape, self.frame.shape)
        np.testing.assert_array_equal(rendered[:80], self.frame[:80])

    def test_interpolated_lens_is_close_to_full_pixel_warp(self):
        rows, columns = np.mgrid[:480, :640]
        frame = np.stack((columns * 255 / 640, rows * 255 / 480,
                          (rows + columns) * 255 / 1120), axis=-1).astype(np.uint8)
        state = replace(self.state, stretch=0.02, fold=0.3, twist=0.4)
        reference = render_portal(frame, state, 1, grid_step=1)
        optimized = render_portal(frame, state, 1)
        difference = np.abs(reference.astype(np.float32) - optimized.astype(np.float32))
        self.assertLess(difference.mean(), 1)
        self.assertLess(difference[170:280, 260:380].mean(), 1)

    def test_refraction_animates_over_time(self):
        first = render_portal(self.frame, self.state, 1)
        second = render_portal(self.frame, self.state, 1.5)
        self.assertFalse(np.array_equal(first, second))

    def test_no_portal_leaves_frame_untouched(self):
        self.assertIs(render_portal(self.frame, None, 1), self.frame)
        invisible = PortalState(self.state.corners, 0, 1)
        self.assertIs(render_portal(self.frame, invisible, 1), self.frame)

    def test_partially_offscreen_glass_is_clipped(self):
        state = PortalState(((-0.05, 0.2), (0.6, 0.3), (0.7, 0.8), (-0.04, 0.7)), 1, 0.8)
        result = render_portal(self.frame, state, 1)
        self.assertEqual(result.shape, self.frame.shape)
        self.assertTrue(np.isfinite(result).all())

    def test_filters_have_different_outputs_and_keep_camera_outside_intact(self):
        rows, columns = np.mgrid[:480, :640]
        frame = np.stack((columns % 256, rows % 256, (columns + rows * 2) % 256), axis=-1).astype(np.uint8)
        outputs = []
        for index, details in enumerate(PORTAL_FILTERS):
            with self.subTest(filter=details[0]):
                state = replace(self.state, stretch=(index + 0.35) / len(PORTAL_FILTERS))
                result = render_portal(frame, state, 2)
                self.assertEqual(result.dtype, np.uint8)
                np.testing.assert_array_equal(result[:80], frame[:80])
                outputs.append(result.tobytes())
        self.assertEqual(len(set(outputs)), len(PORTAL_FILTERS))

    def test_monochrome_filter_removes_color_in_portal_interior(self):
        frame = np.zeros_like(self.frame)
        frame[:] = (220, 85, 30)
        state = replace(self.state, stretch=1.35 / len(PORTAL_FILTERS))
        rendered = render_portal(frame, state, 1)
        interior = rendered[200:240, 280:350]
        np.testing.assert_array_equal(interior[:, :, 0], interior[:, :, 1])
        np.testing.assert_array_equal(interior[:, :, 1], interior[:, :, 2])
        np.testing.assert_array_equal(rendered[:80], frame[:80])

    def test_hand_rotation_twists_even_the_lens_filter_in_both_directions(self):
        state = replace(self.state, stretch=0.02)
        neutral = render_portal(self.frame, replace(state, twist=0), 1)
        clockwise = render_portal(self.frame, replace(state, twist=0.6), 1)
        anticlockwise = render_portal(self.frame, replace(state, twist=-0.6), 1)
        self.assertFalse(np.array_equal(neutral, clockwise))
        self.assertFalse(np.array_equal(clockwise, anticlockwise))

    def test_filter_boundary_does_not_pop_to_another_image(self):
        for boundary in range(1, len(PORTAL_FILTERS)):
            with self.subTest(boundary=boundary):
                stretch = boundary / len(PORTAL_FILTERS)
                before = render_portal(self.frame, replace(self.state, stretch=stretch - 0.0001), 1)
                after = render_portal(self.frame, replace(self.state, stretch=stretch + 0.0001), 1)
                difference = np.abs(before.astype(np.float32) - after.astype(np.float32)).mean()
                self.assertLess(difference, 1)


if __name__ == "__main__":
    unittest.main()
