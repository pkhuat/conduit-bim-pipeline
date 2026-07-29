"""Tests for the live digital-twin reconstruction (webapp/live_twin.py).

Runs headless — no machine, no serial — by feeding LiveTwin a synthetic stream of
(feed_mm, bend_deg, roll_deg) samples like the ones the real STATUS poll produces.

    python3 test_live_twin.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp"))
import live_twin as lt


def test_parse_status_reads_position_and_torque():
    s = lt.parse_status("OK MOVING torque=12% pos=390140")
    assert s["state"] == "MOVING", s
    assert s["pos"] == 390140, s
    assert s["torque"] == 12, s
    idle = lt.parse_status("OK IDLE torque=0% pos=-5")
    assert idle["state"] == "IDLE" and idle["pos"] == -5, idle
    # a bare reply (e.g. no-hardware fallback) must not crash
    bare = lt.parse_status("OK")
    assert bare["pos"] is None, bare


def _feed(tw, feed, bend, roll):
    return tw.update(feed, bend, roll)


def test_offset_reconstructs_two_bends():
    """Jog an offset by hand: feed, bend 30 & release, feed, roll 180, bend 30 &
    release, feed out — expect two locked 30 degree bends, the second rolled 180."""
    tw = lt.LiveTwin()
    _feed(tw, 0, 0, 0)        # session origin
    _feed(tw, 300, 0, 0)      # feed 300 mm
    _feed(tw, 300, 15, 0)     # bend arm rising
    _feed(tw, 300, 30, 0)     # peak 30
    _feed(tw, 300, 10, 0)     # arm coming back (not released yet)
    _feed(tw, 300, 0, 0)      # released -> commit bend #1
    _feed(tw, 600, 0, 0)      # feed another 300
    _feed(tw, 600, 0, 180)    # roll 180 for the return bend
    _feed(tw, 600, 30, 180)   # peak 30
    snap = _feed(tw, 600, 0, 180)   # released -> commit bend #2
    _feed(tw, 800, 0, 180)    # feed out 200

    b = tw.committed
    assert len(b) == 2, f"expected 2 bends, got {len(b)}: {b}"
    assert abs(b[0]["advance"] - 300) < 1 and abs(b[0]["angle"] - 30) < 0.1, b[0]
    assert b[0]["rotate"] == 0, b[0]
    assert abs(b[1]["advance"] - 300) < 1 and abs(b[1]["angle"] - 30) < 0.1, b[1]
    assert abs(b[1]["rotate"] - 180) < 1 and b[1]["roll_dir"] == 1, b[1]


def test_snapshot_shows_bend_forming_before_commit():
    """A bend still being made shows up live as the last segment (before release)."""
    tw = lt.LiveTwin()
    _feed(tw, 0, 0, 0)
    _feed(tw, 250, 0, 0)
    snap = _feed(tw, 250, 22, 0)   # mid-bend, not released
    assert snap["forming"] is True, snap
    assert snap["n_bends"] == 0, snap                 # nothing committed yet
    assert len(snap["path"]["verts"]) >= 3, snap["path"]
    assert snap["path"]["angles"][-1] == 22.0, snap["path"]["angles"]


def test_feed_only_makes_a_straight_no_bends():
    tw = lt.LiveTwin()
    _feed(tw, 0, 0, 0)
    snap = _feed(tw, 500, 0, 0)
    assert snap["n_bends"] == 0 and snap["forming"] is False, snap
    assert all(a == 0 for a in snap["path"]["angles"]), snap["path"]["angles"]


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa
            print(f"ERROR {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)


if __name__ == "__main__":
    main()
