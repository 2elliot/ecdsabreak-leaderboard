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


def row(e, layer=1, day="2026-11-07"):
    return {"entry": e, "layer": layer, "pst_day": day}


def data(ranked=(), unranked=()):
    return {"url": "https://board.example", "phase": "open", "baseline": [{"entry": LINE}], "ranked": list(ranked), "unranked": list(unranked)}


assert build.beats(entry("a", "m", 3, "e", 50, 900), LINE), "lower on both beats"
assert build.beats(entry("a", "m", 3, "e", 100, 900), LINE), "equal on one and lower on the other beats"
assert not build.beats(entry("a", "m", 3, "e", 50, 1100), LINE), "a higher cost doesn't beat"
assert not build.beats(entry("a", "m", 3, "e", 100, 1000), LINE), "equal on both doesn't beat"

first, later = entry("a", "m1", 3, "eval-b", 50, 900), entry("b", "m2", 4, "eval-a", 50, 800)
assert build.holder([row(first), row(later)], LINE, "lowered_t") is later, "a tie goes to the lower other cost"
same = entry("c", "m3", 3, "eval-a", 50, 900)
assert build.holder([row(first), row(same)], LINE, "lowered_t") is same, "on an exact tie, the earlier in board order"
trade_off = entry("d", "m4", 5, "eval-c", 10, 1100)
assert build.holder([row(trade_off), row(first)], LINE, "lowered_t") is first, "a trade-off can't hold an award"
assert build.holder([row(trade_off)], LINE, "lowered_t") is None, "nothing holds with no entry beating the reference"

planted = entry("<script>x</script>", "<img src=x onerror=alert(1)>", 5, "eval-d", 50, 900)
text = build.page(data([row(planted)], [{"entry": planted, "reason": "SAME_COST"}]), NOW)
assert "<script>x" not in text and "<img src=x" not in text, "board text is escaped"
assert "logo.png" in text, "the header displays the logo"
assert "Closes Thursday 2026-11-12, 11:59 PM PST<" in text, "the header gives the close in words"
assert 'data-close="2026-11-12T23:59:00-08:00"' in text, "the countdown runs to standings.py's close, 2026-11-13T07:59:00 UTC"

linked = entry("jack", "comp-iwnlcern-pr2-0927a5b09823", 5, "eval-e", 50, 900)
assert "ecdsafail-v2-reference/pull/2" in build.page(data([row(linked)]), NOW), "an entry links its pull request"
assert "/pull/" not in build.entry_cell(entry("x", "comp-a-pr2-notahexhead", 5, "e", 1, 1)), "only the bot's name form links"

text = build.page(data([row(entry("p", "slow-t", 3, "e1", 90, 100), day="2026-11-07"), row(entry("q", "fast-t", 3, "e2", 10, 990), day="2026-11-10")]), NOW)
by_t, by_qubit_time = text.split("By qubit-time</h3>")
assert by_t.index("fast-t") < by_t.index("slow-t"), "the T table puts the lowest T first"
assert by_qubit_time.index("slow-t") < by_qubit_time.index("fast-t"), "the qubit-time table puts the lowest qubit-time first"
for table, leader, trailer, gap in ((by_t, "fast-t", "slow-t", "+800%"), (by_qubit_time, "slow-t", "fast-t", "+890%")):
    rows = table.split("<tr")
    assert any("slow-t" in r and '"2026-11-07">Nov 7<' in r for r in rows), "each row shows its own entry's day"
    assert any("fast-t" in r and '"2026-11-10">Nov 10<' in r for r in rows), "each row shows its own entry's day"
    assert any(leader in r and ">—<" in r for r in rows), "the best row has no gap to show"
    assert any(trailer in r and f">{gap}<" in r for r in rows), "every other row shows its gap to the best in its table"
assert "Grey rows" not in text and "class=behind" not in text, "nothing is grey while every entry beats the reference"

loser = entry("r", "loses", 3, "e3", 50, 1100)
text = build.page(data([row(entry("p", "slow-t", 3, "e1", 90, 100)), row(loser)]), NOW)
rows = text.split("<tr")
assert any("loses" in r and r.startswith(" class=behind>") for r in rows), "a row that doesn't beat the reference is grey"
assert not any("slow-t" in r and "class=behind" in r for r in rows), "a row that beats the reference isn't grey"
assert "Grey rows" in text, "the page says what grey means"
assert ">+1,000%<" in text, "a gap of 100% or more rounds to a whole percent, with a thousands separator"
assert ">+80.00%<" in text, "a gap under 100% keeps two decimals"

empty = build.page(data(unranked=[{"entry": LINE, "reason": "BASELINE_FAILED"}]), NOW)
assert "No ranked entries yet" in empty and "Nobody yet" in empty, "an empty board renders"
assert "Listed, not ranked" not in empty, "the operator's own failed baseline rows stay off the page"
for low, high, least in ((2.1e7, 5.4e7, 4), (3e9, 2e11, 4), (1e2, 1e9, 4), (0.94e7, 1.06e7, 1)):
    ticks = build.log_ticks(low, high)
    assert least <= len(ticks) <= 8 and all(low <= t <= high for t in ticks), f"log ticks fit {low}..{high}: {ticks}"

chart = build.frontier_chart([row(entry("p", "on-front", 3, "e1", 90, 100)), row(entry("q", "behind", 3, "e2", 95, 500), layer=2)], LINE)
assert chart.count('class="pt front"') == 1 and chart.count('class="pt back"') == 1 and chart.count('class="pt ref"') == 1, "the chart marks the frontier, the rest, and the reference"
assert 'class="step" d="M' in chart, "the chart draws the frontier"
twins = build.frontier_chart([row(entry("p", "a", 3, "e1", 90, 100)), row(entry("q", "b", 3, "e2", 90, 100))], LINE)
assert twins.count('class="pt front"') == 1 and "p · a" in twins and "q · b" in twins, "entries at the same spot share one mark and one tooltip"
alone = build.frontier_chart([], LINE)
assert 'class="step"' not in alone and 'class="pt ref"' in alone, "an empty board charts only the reference"
print("ok")
