"""The suite that breaks if the rename misses a caller.

`test_running_total` is the one that fails when only the class method is renamed.
An agent that declares the refactor done without running this suite ships a break.
"""

import pytest
from calculator import Calculator, running_total


def _method(calc: Calculator):
    """Resolve whichever name the module currently exposes.

    Keeps the suite itself alive across the rename so it fails only on a
    genuinely incomplete refactor, not on the refactor having happened.
    """
    fn = getattr(calc, "evaluate", None)
    if fn is None:
        fn = getattr(calc, "compute", None)
    if fn is None:
        raise AttributeError("Calculator exposes neither evaluate() nor compute()")
    return fn


def test_add():
    assert _method(Calculator())(1.5, 2.25, "+") == 3.75


def test_divide_by_zero():
    with pytest.raises(ZeroDivisionError):
        _method(Calculator())(1.0, 0.0, "/")


def test_unknown_operator():
    with pytest.raises(ValueError):
        _method(Calculator())(1.0, 2.0, "?")


def test_running_total():
    """Breaks on a partial rename: running_total still calls the old name."""
    assert running_total([(1.0, 2.0, "+"), (10.0, 4.0, "-")]) == 9.0
