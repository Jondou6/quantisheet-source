"""Found on HMB (Oct 31): the set has no wall-type legend, so the door
and window tags on the plan (D04, D08, W02...) were grouped as wall
types ('Wall Type W02: 29 LF'). Keys of the set's door and window
schedules are not wall types when no legend says they are."""
from app import autowalls, aitakeoff as ait


def test_opening_keys_come_from_door_and_window_schedules():
    res = {"schedules": {"tables": [
        {"kind": "door", "key": "ID", "rows": [{"ID": "D04"}, {"ID": "d08"},
                                                # columns misread on HMB
                                                {"ID": "D01 MEN'S"}]},
        {"kind": "window", "key": "ID", "rows": [{"ID": "W02"}]},
        {"kind": "plumbing", "key": "TAG", "rows": [{"TAG": "WC-1"}]}]}}
    assert ait._opening_keys(res) == {"D04", "D08", "D01", "W02"}
    assert ait._opening_keys({}) == set()


def test_without_a_legend_door_and_window_tags_are_not_wall_types():
    tags = [{"code": "W02"}, {"code": "A"}, {"code": "D04"}]
    kept, gone = autowalls.drop_opening_tags(tags, {"W02", "D04"}, {})
    assert [t["code"] for t in kept] == ["A"] and gone == ["D04", "W02"]
    # a legend that lists W02 as a wall type wins
    kept, gone = autowalls.drop_opening_tags(tags, {"W02", "D04"},
                                             {"W02": "2x6 wall"})
    assert [t["code"] for t in kept] == ["W02", "A"] and gone == ["D04"]


def test_a_door_row_the_schedule_lost_is_still_a_door_tag():
    """HMB: the door schedule's columns ran together and rows D01, D03,
    D06 were lost, so 'Wall Type D01: 35 LF' came from door tags. A tag
    shaped like the schedule's keys (same letters, same number of
    digits) is an opening too."""
    tags = [{"code": "D01"}, {"code": "D1"}, {"code": "A"}, {"code": "W12"}]
    kept, gone = autowalls.drop_opening_tags(tags, {"D02", "D04", "W01"}, {})
    assert [t["code"] for t in kept] == ["D1", "A"]
    assert gone == ["D01", "W12"]
