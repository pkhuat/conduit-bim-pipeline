"""Guard the simulator against drift from machine_functions.py.

SimMachine subclasses Machine but deliberately skips Machine.__init__ (no serial
ports). That means every time Machine gains new state or methods, SimMachine can
silently fall out of sync — exactly what happened when machine_functions.py added
self._enabled and every enable/disable call started raising AttributeError only in
simulation. These tests exercise the real high-level API against a fresh SimMachine
so that kind of drift fails here, loudly, instead of mid-demo.

    python3 test_sim_machine.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from machine.sim_machine import SimMachine
from machine.commands import Machine


def test_simmachine_init_mirrors_machine_state():
    """SimMachine.__init__ must re-create the plain state the inherited methods use,
    since it skips Machine.__init__. This is the guard that would have caught the
    missing self._enabled."""
    m = SimMachine(verbose=False)
    for attr in ("_enabled", "_lock", "_log_file", "_polling", "axes", "history"):
        assert hasattr(m, attr), f"SimMachine.__init__ is missing '{attr}'"
    assert isinstance(m._enabled, set)


def test_simmachine_runs_the_real_high_level_api():
    """Drive a representative slice of Machine's public API through a fresh
    SimMachine end to end — any state drift surfaces as an AttributeError here."""
    m = SimMachine(verbose=False)
    m.advance_enable(); m.advance_by(100); m.advance_to(0); m.advance_disable()
    m.rotate_enable(); m.rotate_to(90); m.rotate_disable()
    m.bend_enable(); m.bend_to(30); m.bend_to(0); m.bend_disable()
    m.squeeze_enable(); m.squeeze_close(); m.squeeze_open(); m.squeeze_disable()
    m.chuck_enable(); m.chuck_jog(50); m.chuck_disable()
    assert len(m.history) > 0                     # commands actually went through


def test_bend_one_drives_a_pipeline_bend():
    """The pipeline->machine bridge: bend_one() runs a bend (feed/roll/angle from a
    job.json bend) cleanly, with no moving-a-disabled-axis warnings."""
    from run_stick_job import bend_one
    m = SimMachine(verbose=False)
    bend_one(m, feed=500.0, angle=45.0, roll=90.0)
    cmds = [c for _, c, _ in m.history]
    assert any(c.startswith("ADVANCE BY") for c in cmds)
    assert any(c.startswith("ROTATE TO 90") for c in cmds)
    assert any(c.startswith("BEND TO 45") for c in cmds)
    assert not m.warnings                          # every move happens while enabled


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {t.__name__}: {e!r}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
