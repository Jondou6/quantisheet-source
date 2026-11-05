"""Runs last: the isolation guard (conftest) saw nothing during the whole
Back Office suite (brief test 1.2)."""
from . import conftest


def test_1_2_guard_saw_nothing_all_suite():
    assert conftest.GUARD["installed"]
    assert conftest.GUARD["violations"] == []
    assert conftest.GUARD["net"] == []
