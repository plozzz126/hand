import unittest
from types import SimpleNamespace

import numpy as np

from gesture_lab.tracking import HandTracker, OneEuroFilter


def hand(horizontal):
    points = [SimpleNamespace(x=horizontal, y=0.5, z=0.0) for _ in range(21)]
    points[0].y = 0.7
    points[9].y = 0.52
    points[5].x -= 0.04
    points[17].x += 0.04
    return points


def side(name):
    return [SimpleNamespace(category_name=name, score=0.99)]


class OneEuroTests(unittest.TestCase):
    def test_stationary_joint_jitter_is_reduced(self):
        adaptive = OneEuroFilter()
        raw, smoothed = [], []
        for frame in range(90):
            point = 0.5 + (0.003 if frame % 2 else -0.003)
            result = adaptive.update([[point, 0.5, 0]], frame / 30)
            if frame > 20:
                raw.append(point)
                smoothed.append(result[0, 0])
        self.assertLess(np.std(smoothed), np.std(raw) * 0.5)

    def test_fast_motion_is_not_given_the_stationary_filter_delay(self):
        adaptive = OneEuroFilter()
        for frame in range(10):
            adaptive.update([[0.2, 0.5, 0]], frame / 30)
        moved = adaptive.update([[0.5, 0.5, 0]], 10 / 30)
        self.assertGreater(moved[0, 0], 0.44)

    def test_long_loss_resets_without_dragging_old_skeleton(self):
        adaptive = OneEuroFilter()
        adaptive.update([[0.1, 0.2, 0]], 0)
        np.testing.assert_allclose(adaptive.update([[0.8, 0.9, 0]], 1), [[0.8, 0.9, 0]])

    def test_repeated_timestamp_does_not_produce_nan(self):
        adaptive = OneEuroFilter()
        first = adaptive.update([[0.2, 0.3, 0]], 1)
        np.testing.assert_array_equal(adaptive.update([[0.9, 0.8, 0]], 1), first)


class HandAssociationTests(unittest.TestCase):
    def test_detection_order_changes_do_not_swap_joint_filters(self):
        tracker = HandTracker()
        first = tracker.update([hand(0.2), hand(0.8)], [side("Left"), side("Right")], [], 0)
        second = tracker.update([hand(0.79), hand(0.21)], [side("Right"), side("Left")], [], 0.033)
        self.assertEqual([tracked.track_id for tracked in first], [tracked.track_id for tracked in second])
        self.assertLess(second[0].landmarks[0].x, 0.3)
        self.assertGreater(second[1].landmarks[0].x, 0.7)
        self.assertEqual(second[0].source_index, 1)

    def test_crossing_hands_keep_their_identities(self):
        tracker = HandTracker()
        identities = None
        for frame in range(21):
            positions = [hand(0.2 + frame * 0.025), hand(0.8 - frame * 0.025)]
            labels = [side("Left"), side("Right")]
            if frame % 2:
                positions.reverse()
                labels.reverse()
            tracked = tracker.update(positions, labels, [], frame / 30)
            if identities is None:
                identities = [tracked[0].track_id, tracked[1].track_id]
            self.assertEqual([tracked[0].track_id, tracked[1].track_id], identities)
        self.assertGreater(tracked[0].landmarks[0].x, tracked[1].landmarks[0].x)

    def test_short_occlusion_reuses_identity_without_inventing_visible_hand(self):
        tracker = HandTracker()
        first = tracker.update([hand(0.2), hand(0.8)], [side("Left"), side("Right")], [], 0)
        single = tracker.update([hand(0.79)], [side("Right")], [], 0.033)
        self.assertEqual(len(single), 1)
        self.assertEqual(single[0].track_id, first[1].track_id)
        restored = tracker.update([hand(0.21), hand(0.78)], [side("Left"), side("Right")], [], 0.066)
        self.assertEqual([tracked.track_id for tracked in restored], [tracked.track_id for tracked in first])

    def test_empty_or_invalid_detections_do_not_leave_ghost_hands(self):
        tracker = HandTracker()
        tracker.update([hand(0.2)], [side("Left")], [], 0)
        self.assertEqual(tracker.update([], [], [], 0.033), [])
        invalid = hand(0.2)
        invalid[8].x = float("nan")
        self.assertEqual(tracker.update([invalid], [], [], 0.066), [])

    def test_sudden_handedness_label_error_does_not_teleport_joints(self):
        tracker = HandTracker()
        first = tracker.update([hand(0.2), hand(0.8)], [side("Left"), side("Right")], [], 0)
        second = tracker.update([hand(0.21), hand(0.79)], [side("Right"), side("Left")], [], 0.033)
        self.assertEqual([tracked.track_id for tracked in second], [tracked.track_id for tracked in first])
        self.assertEqual([tracked.handedness for tracked in second], ["Left", "Right"])


if __name__ == "__main__":
    unittest.main()
