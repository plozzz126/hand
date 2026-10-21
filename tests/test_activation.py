import unittest
from copy import deepcopy

from test_portal import two_hands

from gesture_lab.activation import ContactToggle, fingertip_contact
from gesture_lab.portal import PortalTracker


def touching_hands():
    hands = two_hands()
    for landmarks in hands:
        landmarks[8].x = 0.5
        landmarks[8].y = 0.29
        landmarks[4].x = 0.5
        landmarks[4].y = 0.64
    return hands


class ContactToggleTests(unittest.TestCase):
    def setUp(self):
        self.toggle = ContactToggle()
        self.now = 0.0

    def feed(self, hands, frames=8):
        changes = []
        for _ in range(frames):
            self.toggle.update(hands, 640, 480, self.now)
            if self.toggle.changed:
                changes.append(self.toggle.enabled)
            self.now += 0.04
        return changes

    def test_open_hands_do_not_activate_effect_automatically(self):
        self.assertEqual(self.feed(two_hands(), 50), [])
        self.assertFalse(self.toggle.enabled)

    def test_only_both_matching_fingertip_pairs_count_as_contact(self):
        for finger in (4, 8):
            hands = touching_hands()
            hands[1][finger].x += 0.15
            with self.subTest(separated_finger=finger):
                self.assertEqual(self.feed(hands), [])
                self.assertFalse(self.toggle.enabled)
        self.assertEqual(self.feed(touching_hands()), [True])

    def test_holding_contact_triggers_exactly_once(self):
        self.assertEqual(self.feed(touching_hands(), 100), [True])
        self.assertTrue(self.toggle.enabled)

    def test_second_contact_disables_and_third_reenables(self):
        self.assertEqual(self.feed(touching_hands()), [True])
        self.feed(two_hands())
        self.assertEqual(self.feed(touching_hands()), [False])
        self.feed(two_hands())
        self.assertEqual(self.feed(touching_hands()), [True])

    def test_brief_accidental_contact_does_not_toggle(self):
        self.assertEqual(self.feed(touching_hands(), 2), [])
        self.feed(two_hands())
        self.assertFalse(self.toggle.enabled)

    def test_hand_loss_does_not_rearm_a_contact_that_is_still_held(self):
        self.feed(touching_hands())
        self.feed([], 20)
        self.assertEqual(self.feed(touching_hands()), [])
        self.assertTrue(self.toggle.enabled)

    def test_contact_jitter_after_occlusion_does_not_rearm(self):
        self.feed(touching_hands())
        self.feed([], 3)
        jittered = touching_hands()
        jittered[1][8].x += 0.05
        jittered[1][4].x += 0.05
        self.assertGreater(fingertip_contact(jittered, 640, 480), 1)
        self.assertLess(fingertip_contact(jittered, 640, 480), 1.7)
        self.feed(jittered, 20)
        self.assertEqual(self.feed(touching_hands()), [])

    def test_camera_pause_does_not_complete_contact_hold(self):
        self.feed(touching_hands(), 1)
        self.now += 1
        self.assertEqual(self.feed(touching_hands(), 1), [])
        self.assertFalse(self.toggle.enabled)

    def test_single_hand_and_all_fingertips_collapsed_do_not_toggle(self):
        self.assertIsNone(fingertip_contact(touching_hands()[:1], 640, 480))
        collapsed = touching_hands()
        for landmarks in collapsed:
            landmarks[4] = deepcopy(landmarks[8])
        self.assertIsNone(fingertip_contact(collapsed, 640, 480))
        self.assertEqual(self.feed(collapsed), [])

    def test_gate_controls_real_portal_and_can_be_used_repeatedly(self):
        tracker = PortalTracker()

        def sequence(hands, frames=8):
            state = None
            for _ in range(frames):
                enabled = self.toggle.update(hands, 640, 480, self.now)
                if self.toggle.changed:
                    tracker.reset()
                state = tracker.update(hands, 640, 480, self.now) if enabled else None
                self.now += 0.04
            return state

        self.assertIsNone(sequence(two_hands()))
        for _ in range(3):
            sequence(touching_hands())
            self.assertIsNotNone(sequence(two_hands()))
            sequence(touching_hands())
            self.assertIsNone(sequence(two_hands()))


if __name__ == "__main__":
    unittest.main()
