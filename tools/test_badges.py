"""Offline tests for game/badges.py: bubbles read in waves (user D189) - wave 1 the badge corner ("!" ready / water drop /
none) against a small embedding store, wave 2 the icon with the badge masked. Run: .venv/bin/python tools/test_badges.py"""
import os
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game import affordances as AF, badges as B, experience as X, icons, integrate as I  # noqa: E402

BEIGE = (222, 206, 186)


def bubble(badge=None, icon=(80, 160, 70)):
    """A 140-px bubble crop: beige disc, an icon blob in the middle, a badge at the top right."""
    im = Image.new('RGB', (140, 140), (90, 60, 40))
    d = ImageDraw.Draw(im)
    d.ellipse((18, 18, 122, 122), fill=BEIGE)
    d.ellipse((50, 45, 90, 95), fill=icon)
    if badge == 'ready':
        d.ellipse((104, 10, 132, 38), fill=(240, 150, 60))
        d.rectangle((116, 15, 120, 27), fill=(255, 255, 255))
    elif badge == 'drop':
        d.ellipse((104, 10, 132, 38), fill=(150, 215, 245))
    return im


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        p = mock.patch.object(B, 'DIR', os.path.join(self.tmp, 'badges'))
        p.start()
        self.addCleanup(p.stop)
        B.reset()
        self.addCleanup(B.reset)


class Store(Base):
    def test_an_empty_store_reads_nothing(self):
        self.assertIsNone(B.read(bubble('ready')))

    def test_the_corner_is_read_against_the_labelled_examples(self):
        B.add('ready', bubble('ready', icon=(80, 160, 70)), 'test')
        B.add('none', bubble(None, icon=(80, 160, 70)), 'test')
        B.add('drop', bubble('drop', icon=(80, 160, 70)), 'test')
        self.assertEqual(B.read(bubble('ready', icon=(90, 120, 230))), 'ready')   # another crop, same badge
        self.assertEqual(B.read(bubble(None, icon=(240, 140, 60))), 'none')
        self.assertEqual(B.read(bubble('drop', icon=(200, 40, 40))), 'drop')

    def test_one_label_alone_decides_nothing(self):
        """Only `none` examples (the first proven case) would read every "!" as none: no decision yet."""
        B.add('none', bubble(None), 'test')
        self.assertIsNone(B.read(bubble('ready')))
        self.assertIsNone(B.read(bubble(None)))

    def test_labels_outside_the_vocabulary_are_refused(self):
        with self.assertRaises(ValueError):
            B.add('ready_bean', bubble('ready'), 'test')


class IconWave(unittest.TestCase):
    def test_the_icon_vector_ignores_the_badge(self):
        a, b = bubble(None), bubble('ready')
        self.assertEqual(icons._vec(icons.inner(a)), icons._vec(icons.inner(b)))

    def test_crops_are_centred_on_the_bubble_disc(self):
        """Live D189: the bubble point is up to ~20 px off the disc centre; fixed crops cut different parts."""
        frame = Image.new('RGB', (400, 400), (90, 60, 40))
        frame.paste(bubble('ready'), (150, 150))          # disc centre at (220, 220)
        cx, cy = icons.disc_centre(frame, (200, 238))     # the finder's point, off by (-20, +18)
        self.assertLess(abs(cx - 220) + abs(cy - 220), 6, (cx, cy))
        got = icons.bubble140(frame, (200, 238))              # cropped around the disc centre, not the finder's point
        on = frame.crop((150, 150, 290, 290))
        self.assertLess(icons._dist(icons._vec(icons.inner(got)), icons._vec(icons.inner(on))), 0.05)


class Scan(Base):
    def wf(self, crop):
        frame = Image.new('RGB', (1920, 1080), (90, 60, 40))
        frame.paste(crop, (890, 470))   # the bubble on the frame, its disc centred at (960, 540)

        class W:
            find_bubbles = staticmethod(lambda img: [(960, 540)])
            bubble_kind = staticmethod(lambda img, b: ('water', 0.1))
            bubble_crop = staticmethod(lambda img, b: crop)
            bubble_highlighted = staticmethod(lambda img, b: False)
            grab = staticmethod(lambda: frame)
        return W

    def test_wave_one_decides_ready_and_drop_when_the_store_knows_the_badge(self):
        B.add('ready', bubble('ready'), 'test')
        B.add('none', bubble(None), 'test')
        with mock.patch.object(AF.core, 'WF', self.wf(bubble('ready', icon=(90, 120, 230)))):
            a, = AF.scan()
        self.assertTrue(a.ready)
        self.assertFalse(a.drop)
        self.assertEqual(a.badge, 'ready')

    def test_a_water_drop_is_never_read_as_ready(self):
        """Live D189 17:50: with ready/none examples only, the carrot's drop corner read `ready` - it got watered."""
        B.add('ready', bubble('ready'), 'test')
        B.add('none', bubble(None), 'test')
        with mock.patch.object(AF.core, 'WF', self.wf(bubble('drop'))), mock.patch.object(B, 'read', lambda c: 'ready'):
            a, = AF.scan()
        self.assertEqual((a.drop, a.ready), (True, False))

    def test_an_empty_store_falls_back_to_the_colour_readers(self):
        with mock.patch.object(AF.core, 'WF', self.wf(bubble('drop'))), \
                mock.patch.object(AF, 'has_drop', lambda c: True), mock.patch.object(AF, 'has_ready', lambda c: False):
            a, = AF.scan()
        self.assertEqual((a.drop, a.ready, a.badge), (True, False, None))


class ColourFallback(unittest.TestCase):
    """Until the store knows the badge: the "!" at ~(117, 24) of the 140-px crop (live D189 bean/tulip crops) - the
    old window at (105, 35) caught only part of it."""

    def test_the_badge_where_it_sits_is_ready(self):
        self.assertTrue(AF.has_ready(bubble('ready')))

    def test_a_plain_bubble_is_not_ready(self):
        self.assertFalse(AF.has_ready(bubble(None)))


class Learning(Base):
    """Click results label the corner (the integrator's memory consumer): Collect = ready, a crop card's days left =
    none, a water event = drop."""

    def exp(self, **ev):
        return X.Experience.new(action=X.Action('click', 'bubble', (960, 540)), evidence=X.Evidence(**ev),
                                verdict=X.Verdict('unknown'), artifacts=X.Artifacts(log_mark=1, t=1.0))

    def labels(self, e):
        return [u.args.get('label') for u in I.propose(e).memory if u.op == 'badge']

    def test_collect_labels_ready(self):
        e = X.Experience.new(prediction=X.Prediction(card='Collect'), action=X.Action('click', 'bubble', (960, 540)),
                             evidence=X.Evidence(texts=('Collect',)),
                             verdict=X.Verdict('hit', (X.Check('card', 'Collect', 'Collect', True),)),
                             artifacts=X.Artifacts(log_mark=1, t=1.0))
        self.assertEqual(self.labels(e), ['ready'])

    def test_a_days_left_card_labels_none_and_water_labels_drop(self):
        self.assertEqual(self.labels(self.exp(burst_texts=('Carrot', 'A crisp orange vegetable', '2 days remaining'))),
                         ['none'])
        self.assertEqual(self.labels(self.exp(events=('water',))), ['drop'])
        self.assertEqual(self.labels(self.exp(events=('plant_growing',))), [])   # no proof: nothing stored


if __name__ == '__main__':
    unittest.main()
