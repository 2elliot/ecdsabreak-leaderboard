#!/usr/bin/env python3
"""Run: python3 -I test_build.py"""
import datetime
import importlib.util
import os

spec = importlib.util.spec_from_file_location("build", os.path.join(os.path.dirname(os.path.abspath(__file__)), "build.py"))
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

LINE = {"user": "operator-check", "method": "reference-c4", "round_id": 2, "evaluation": "eval-r", "lowered_t": 100, "qubit_time": 1000, "f": 0, "boundary_failing": 0}
NOW = datetime.datetime(2026, 11, 8, tzinfo=datetime.timezone.utc)


def entry(user, method, round_id, evaluation, t, qubit_time):
    return {"user": user, "method": method, "round_id": round_id, "evaluation": evaluation, "lowered_t": t, "qubit_time": qubit_time, "f": 0, "boundary_failing": 0}


def row(e, layer=1):
    return {"entry": e, "layer": layer}


def data(ranked=(), unranked=()):
    return {"url": "https://board.example", "phase": "open", "baseline": [{"entry": LINE}], "ranked": list(ranked), "unranked": list(unranked)}


assert build.beats(entry("a", "m", 3, "e", 50, 900), LINE), "lower on both beats"
assert build.beats(entry("a", "m", 3, "e", 100, 900), LINE), "equal on one and lower on the other beats"
assert not build.beats(entry("a", "m", 3, "e", 50, 1100), LINE), "a higher cost doesn't beat"
assert not build.beats(entry("a", "m", 3, "e", 100, 1000), LINE), "equal on both doesn't beat"

first, later = entry("a", "m1", 3, "eval-b", 50, 900), entry("b", "m2", 4, "eval-a", 50, 800)
assert build.holder([row(later), row(first)], LINE, "lowered_t") is first, "a tie goes to the earlier round"
same = entry("c", "m3", 3, "eval-a", 50, 950)
assert build.holder([row(first), row(same)], LINE, "lowered_t") is same, "in one round, the lower evaluation id"
trade_off = entry("d", "m4", 5, "eval-c", 10, 1100)
assert build.holder([row(trade_off), row(first)], LINE, "lowered_t") is first, "a trade-off can't hold an award"
assert build.holder([row(trade_off)], LINE, "lowered_t") is None, "nothing holds with no entry beating the reference"

planted = entry("<script>x</script>", "<img src=x onerror=alert(1)>", 5, "eval-d", 50, 900)
text = build.page(data([row(planted)], [{"entry": planted, "reason": "SAME_COST"}]), NOW)
assert "<script>x" not in text and "<img" not in text, "board text is escaped"

linked = entry("jack", "comp-iwnlcern-pr2-0927a5b09823", 5, "eval-e", 50, 900)
assert "ecdsafail-v2-reference/pull/2" in build.page(data([row(linked)]), NOW), "an entry links its pull request"
assert "/pull/" not in build.entry_cell(entry("x", "comp-a-pr2-notahexhead", 5, "e", 1, 1)), "only the bot's name form links"

empty = build.page(data(unranked=[{"entry": LINE, "reason": "BASELINE_FAILED"}]), NOW)
assert "No ranked entries yet" in empty and "Nobody yet" in empty, "an empty board renders"
assert "Listed, not ranked" not in empty, "the operator's own failed baseline rows stay off the page"
print("ok")
