#!/usr/bin/env python3
"""Competition standings from public board reads. Run: python3 -I standings.py <board-url> [--repo <shared repository clone>]"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime
import enum
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zoneinfo


def utc(text):
    return int(datetime.datetime.fromisoformat(text).replace(tzinfo=datetime.timezone.utc).timestamp())


WINDOW_OPEN = utc("2026-11-07T17:00:00")
WINDOW_CLOSE = utc("2026-11-13T07:59:00")
EARLY_EXACT_OPEN = utc("2026-11-06T08:00:00")
PREFIX = "comp-"
BASELINE_USERS = ("operator-check",)
DAILY_LIMIT = 5
AUDIT_TOP = 10
AUDIT_PER_MEMBER = 3
NOTE_GRACE_SECONDS = 24 * 3600
ZONE = zoneinfo.ZoneInfo("America/Los_Angeles")

READ_GAP_SECONDS = 1.1
BACKOFF_SECONDS = (5, 10, 20, 40, 60, 60, 60)
PAGE_RESTARTS = 8
RETRYABLE_HTTP = (0, 429, 502, 503, 504)
USER_AGENT = "competition-standings/1"
CACHE_VERSION = 1


class State(str, enum.Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    INCOMPLETE = "INCOMPLETE"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"


class Reason(str, enum.Enum):
    BASELINE_FAILED = "baseline row that did not pass"
    PRACTICE = "practice, no comp- prefix"
    CANCELLED = "round cancelled"
    OUTSIDE = "outside the window"
    OVER_LIMIT = "over the daily limit"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected, no test ran"
    TIMED_OUT = "timed out, test passed 120 s"
    INCOMPLETE = "incomplete, no result"
    FAILED = "failed testing"
    NO_COST = "no cost on the board"
    SAME_COST = "same T and qubit-time as an earlier entry by another member, or the baseline"
    NO_NOTE = "no valid note within 24 hours of the round publishing"


class Note(str, enum.Enum):
    UNCHECKED = "not checked"
    FILED = "filed"
    PENDING = "note pending"
    LAPSED = "lapsed"


TERMINAL_REASONS = {"REJECTED": Reason.REJECTED, "TIMED_OUT": Reason.TIMED_OUT, "INCOMPLETE": Reason.INCOMPLETE}


@dataclasses.dataclass(frozen=True)
class Entry:
    user: str
    method: str
    round_id: int
    evaluation: str
    lowered_t: int | None
    qubit_time: int | None
    f: int | None
    n: int | None
    boundary_failing: int | None
    terminal: str | None
    state: State
    published_at: int | None

    @property
    def pst_day(self):
        return None if self.published_at is None else pst_day(self.published_at)


@dataclasses.dataclass(frozen=True)
class Rules:
    window_open: int = WINDOW_OPEN
    window_close: int = WINDOW_CLOSE
    early_exact_open: int = EARLY_EXACT_OPEN
    prefix: str = PREFIX
    baseline_users: tuple = BASELINE_USERS
    daily_limit: int = DAILY_LIMIT


@dataclasses.dataclass(frozen=True)
class Ranked:
    entry: Entry
    layer: int = 0
    note: Note = Note.UNCHECKED
    built_on: tuple = ()


@dataclasses.dataclass(frozen=True)
class Unranked:
    entry: Entry
    reason: Reason


@dataclasses.dataclass(frozen=True)
class Standings:
    ranked: list
    unranked: list
    baseline: list
    phase: str


def pst_day(unix_seconds):
    return datetime.datetime.fromtimestamp(unix_seconds, ZONE).date().isoformat()


def costs(entry):
    return entry.lowered_t, entry.qubit_time


def dominates(a, b):
    """The board's rule: no worse on both costs and better on one, so equal pairs dominate neither way."""
    return a != b and a[0] <= b[0] and a[1] <= b[1]


def beats(entry, reference):
    """The awards' test: lower than the reference on one raw cost and no higher on the other."""
    (t, q), (ref_t, ref_q) = costs(entry), costs(reference)
    return (t < ref_t and q <= ref_q) or (q < ref_q and t <= ref_t)


def layers(pairs):
    """Each distinct pair is 1 plus the highest layer among its dominators, so equal pairs share a layer. Sorted order puts every dominator first. This is `layers_by_definition` from the tests of `pareto_layers` in service/src/consumer.rs."""
    held = {}
    for pair in sorted(set(pairs)):
        held[pair] = 1 + max((layer for other, layer in held.items() if dominates(other, pair)), default=0)
    return [held[pair] for pair in pairs]


def board_place(layer, entry):
    """The board's order of ranked rows."""
    return layer, entry.lowered_t, entry.evaluation


def in_window(entry, rules):
    at = entry.published_at
    if at is None:
        return False
    early_exact = rules.early_exact_open <= at < rules.window_open and entry.state is State.PASSED
    return rules.window_open <= at < rules.window_close or early_exact


def refusal(entry, rules, slots):
    if entry.user in rules.baseline_users:
        return Reason.BASELINE_FAILED
    if not entry.method.startswith(rules.prefix):
        return Reason.PRACTICE
    if entry.state is State.CANCELLED:
        return Reason.CANCELLED
    if not in_window(entry, rules):
        return Reason.OUTSIDE
    slots[entry.user, entry.pst_day] += 1
    if slots[entry.user, entry.pst_day] > rules.daily_limit:
        return Reason.OVER_LIMIT
    if entry.state is State.WITHDRAWN:
        return Reason.WITHDRAWN
    if entry.terminal in TERMINAL_REASONS:
        return TERMINAL_REASONS[entry.terminal]
    if entry.state is not State.PASSED:
        return Reason.FAILED
    if entry.lowered_t is None or entry.qubit_time is None:
        return Reason.NO_COST
    return None


def board_order(entry):
    return entry.round_id, entry.evaluation


def reference_of(baseline):
    """The baseline row an entry must beat: the lowest qubit-time, then the earliest in board order."""
    return min((row.entry for row in baseline), key=lambda entry: (entry.qubit_time, board_order(entry)), default=None)


def ranked_by(cost, other):
    """The one ranking key every branch, award, and audit list uses: the lower `cost`, then on a tie the lower `other` cost, and only on an exact tie the earlier in board order."""
    return lambda entry: (cost(entry), other(entry), board_order(entry))


def lowered_t(entry):
    return entry.lowered_t


def qubit_time(entry):
    return entry.qubit_time


BY_T = ranked_by(lowered_t, qubit_time)
BY_QUBIT_TIME = ranked_by(qubit_time, lowered_t)


def award_holder(rows, reference, key):
    """The row that holds an award as things stand: the first by `key` among the rows that beat the reference, so a tie in the award's cost goes to the lower other cost."""
    if reference is None:
        return None
    return min((row for row in rows if beats(row.entry, reference)), key=lambda row: key(row.entry), default=None)


def on_the_table(entry, rules):
    """Ranked or listed, whatever the rules then decide: every row but the baseline and practice."""
    return entry.user not in rules.baseline_users and entry.method.startswith(rules.prefix)


def note_deadline(entry):
    return entry.published_at + NOTE_GRACE_SECONDS


def note_state(entry, filed, now):
    if filed is None:
        return Note.UNCHECKED
    if entry.evaluation in filed:
        return Note.FILED
    return Note.PENDING if now < note_deadline(entry) else Note.LAPSED


def phase_at(rules, now):
    return "before" if now < rules.window_open else "open" if now < rules.window_close else "closed"


def is_baseline(entry, rules):
    return entry.user in rules.baseline_users and entry.state is State.PASSED


def rank(entries, rules, now, filed=None):
    """`filed` maps the evaluation of each entry with a good note on time to its `notes.Filed`. None means no repository was read, so no note rule applies."""
    ordered = sorted(entries, key=board_order)
    baseline = [Ranked(entry) for entry in ordered if is_baseline(entry, rules)]
    holders = collections.defaultdict(set)
    for row in baseline:
        holders[costs(row.entry)].add(row.entry.user)
    rows, unranked = [], []
    slots = collections.Counter()
    for entry in ordered:
        if is_baseline(entry, rules):
            continue
        reason = refusal(entry, rules, slots)
        if reason is None and holders[costs(entry)] - {entry.user}:
            reason = Reason.SAME_COST
        if reason is None:
            note = note_state(entry, filed, now)
            reason = Reason.NO_NOTE if note is Note.LAPSED else None
        if reason is None:
            holders[costs(entry)].add(entry.user)
            built_on = filed[entry.evaluation].built_on if note is Note.FILED else ()
            rows.append(Ranked(entry, note=note, built_on=built_on))
        else:
            unranked.append(Unranked(entry, reason))
    found = layers([costs(row.entry) for row in rows])
    ranked = sorted((dataclasses.replace(row, layer=layer) for row, layer in zip(rows, found)), key=lambda row: board_place(row.layer, row.entry))
    return Standings(ranked, unranked, baseline, phase_at(rules, now))


def most_built_on(standings, filed):
    """Per member, how many other members' ranked entries descend from that member's entries, through any chain of good notes."""
    parents = {f"{f.entry.user}/{f.entry.method}": f.built_on for f in filed.values()}
    owners = {f"{e.user}/{e.method}": e.user for e in (*(p.entry for p in standings.ranked), *(u.entry for u in standings.unranked))}
    descendants = collections.defaultdict(set)
    for p in standings.ranked:
        seen, waiting = set(), list(p.built_on)
        while waiting:
            name = waiting.pop()
            if name in seen:
                continue
            seen.add(name)
            waiting += parents.get(name, ())
            if name in owners and owners[name] != p.entry.user:
                descendants[owners[name]].add(p.entry.evaluation)
    return sorted(((member, len(rows)) for member, rows in descendants.items()), key=lambda pair: (-pair[1], pair[0]))


def best_per_member(ordered, top, per_member):
    """One member's variants of a circuit must not crowd others out of the audit."""
    taken, picks = collections.Counter(), []
    for row in ordered:
        if len(picks) < top and taken[row.entry.user] < per_member:
            taken[row.entry.user] += 1
            picks.append(row)
    return picks


def audit_picks(ranked, top=AUDIT_TOP, per_member=AUDIT_PER_MEMBER):
    by_t = sorted(ranked, key=lambda row: BY_T(row.entry))
    by_qubit_time = sorted(ranked, key=lambda row: BY_QUBIT_TIME(row.entry))
    picks = best_per_member(by_t, top, per_member) + best_per_member(by_qubit_time, top, per_member)
    return list({p.entry.evaluation: p for p in picks}.values())


class BoardError(Exception):
    pass


Board = collections.namedtuple("Board", "status revision rounds entries attempts")


class Reader:
    def __init__(self, url, cache_path=None, sleep=time.sleep, clock=time.monotonic):
        self.url, self.cache_path, self.sleep, self.clock = url.rstrip("/"), cache_path, sleep, clock
        self.reads, self.backoffs, self.last = 0, [], None
        self.cache = self.load_cache()

    def load_cache(self):
        if self.cache_path is None or not os.path.exists(self.cache_path):
            return {}
        with open(self.cache_path) as source:
            held = json.load(source)
        return held["evaluations"] if held.get("version") == CACHE_VERSION else {}

    def save_cache(self):
        if self.cache_path is None:
            return
        spare = f"{self.cache_path}.{os.getpid()}.new"
        with open(spare, "w") as sink:
            json.dump({"version": CACHE_VERSION, "evaluations": self.cache}, sink)
        os.replace(spare, self.cache_path)

    def fetch(self, path):
        if self.last is not None:
            wait = self.last + READ_GAP_SECONDS - self.clock()
            if wait > 0:
                self.sleep(wait)
        self.last = self.clock()
        self.reads += 1
        request = urllib.request.Request(self.url + path, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except (OSError, http.client.HTTPException) as error:
            return 0, str(error).encode()

    def get(self, path):
        for delay in (*BACKOFF_SECONDS, None):
            status, body = self.fetch(path)
            if status not in RETRYABLE_HTTP:
                return status, body
            if delay is None:
                raise BoardError(f"GET {path} kept failing, last status {status}: {body[:160]!r}")
            self.backoffs.append((status, delay))
            self.sleep(delay)

    def details(self, evaluation):
        key = f"{self.url} {evaluation}"
        if key not in self.cache:
            status, body = self.get(f"/v2/status/{evaluation}")
            if status != 200:
                raise BoardError(f"GET /v2/status/{evaluation} answered {status}: {body[:160]!r}")
            self.cache[key] = parse_status(json.loads(body))
            self.save_cache()
        return self.cache[key]


def parse_status(document):
    details = document["details"]
    cost = details.get("cost") or {}
    seeded = (details.get("test_report") or {}).get("seeded") or {}
    return {
        "method_digest": document["method_digest"],
        "lowered_t": int(cost["lowered_t"]) if cost else None,
        "qubit_time": int(cost["qubit_time"]) if cost else None,
        "accepted": seeded.get("accepted"),
        "terminal": details.get("terminal"),
        "challenge_root": details.get("challenge_root"),
    }


def read_pages(reader):
    entries, attempts, query = [], [], {}
    while True:
        status, body = reader.get("/v2/tested" + ("?" + urllib.parse.urlencode(query) if query else ""))
        if status == 409:
            return None
        if status != 200:
            raise BoardError(f"GET /v2/tested answered {status}: {body[:160]!r}")
        page = json.loads(body)
        entries += page["entries"]
        attempts += page["attempts"]
        if page["entries_next"] is None and page["attempts_next"] is None:
            return Board(page["board_status"], page["board_revision"], page["rounds"], entries, attempts)
        query = {
            "entries_from": page["entries_total"] if page["entries_next"] is None else page["entries_next"],
            "attempts_from": page["attempts_total"] if page["attempts_next"] is None else page["attempts_next"],
            "board_revision": page["board_revision"],
        }


def read_board(reader):
    for _ in range(PAGE_RESTARTS):
        board = read_pages(reader)
        if board is not None:
            if board.status == "CLOSED":
                raise BoardError("the board is CLOSED, which empties its passing rows, so no ranking can be read")
            return board
    raise BoardError(f"the board moved during {PAGE_RESTARTS} reads")


def attempt_state(row):
    if row["cancellation"] is not None:
        return State.CANCELLED
    if row["withdrawals"] or row["outcome"] == "PASSED":
        return State.WITHDRAWN
    return State(row["outcome"])


def needs_status(row, state, published_at, rules):
    in_reach = published_at is not None and rules.early_exact_open <= published_at < rules.window_close
    return row["method_name"].startswith(rules.prefix) and row["user_id"] not in rules.baseline_users and state is not State.CANCELLED and in_reach


def to_entries(board, reader, rules):
    published = {r["round_id"]: r["published_at"] for r in board.rounds}
    rows = [
        Entry(r["user_id"], r["method_name"], r["round_id"], r["evaluation_id"], r["lowered_t"], int(r["qubit_time"]), 0, r["inputs"], 0, None, State.PASSED, published[r["round_id"]])
        for r in board.entries
    ]
    for r in board.attempts:
        state, published_at = attempt_state(r), published[r["round_id"]]
        held = reader.details(r["evaluation_id"]) if needs_status(r, state, published_at, rules) else {}
        rows.append(Entry(r["user_id"], r["method_name"], r["round_id"], r["evaluation_id"], held.get("lowered_t"), held.get("qubit_time"), r["seeded_failing"], held.get("accepted"),
                          r["boundary_failing"], held.get("terminal"), state, published_at))
    return rows


def count(value):
    return f"{value:,}"


def table(rows):
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip() for row in rows)


def ranked_table(standings, checked):
    head = ("layer", "member", "method", "T", "qubit-time")
    rows = [(str(p.layer), p.entry.user, p.entry.method, count(p.entry.lowered_t), count(p.entry.qubit_time)) for p in standings.ranked]
    if not checked:
        return table([head, *rows])
    lineage = lambda p: p.note.value if p.note is Note.PENDING else ", ".join(p.built_on)
    return table([(*head, "built on"), *((*row, lineage(p)) for row, p in zip(rows, standings.ranked))])


def unranked_table(unranked):
    head = ("member", "method", "round", "f", "boundary", "reason")
    number = lambda value: "-" if value is None else str(value)
    return table([head, *((u.entry.user, u.entry.method, str(u.entry.round_id), number(u.entry.f), number(u.entry.boundary_failing), u.reason.value) for u in unranked)])


def report(url, board, standings, filed, clone):
    stamp = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())
    lines = [f"Standings from {url}, read {stamp}, board {board.status}, revision {board.revision[:12]}, window {standings.phase}.",
             "Sampled and unqualified: one controlled addition, not an attack.",
             "Notes not checked: no --repo given." if filed is None else f"Notes checked against {clone}."]
    for p in standings.baseline:
        lines.append(f"Line to beat: {p.entry.user} {p.entry.method}: T {count(p.entry.lowered_t)} and qubit-time {count(p.entry.qubit_time)}.")
    lines += ["", ranked_table(standings, filed is not None) if standings.ranked else "No ranked entries yet."]
    if filed is not None:
        credit = most_built_on(standings, filed)
        lines += ["", "Most built on: " + (", ".join(f"{member} {rows}" for member, rows in credit) if credit else "none yet") + "."]
    listed = [u for u in standings.unranked if u.reason is not Reason.PRACTICE]
    if listed:
        lines += ["", "Listed, not ranked:", unranked_table(listed)]
    lines += ["", f"Practice uploads not listed: {len(standings.unranked) - len(listed)}."]
    return "\n".join(lines)


def jsonable(url, board, standings, reader, filed):
    row = lambda p: {**dataclasses.asdict(p), "pst_day": p.entry.pst_day}
    return {"url": url, "board_status": board.status, "board_revision": board.revision, "phase": standings.phase, "reads": reader.reads, "backoffs": reader.backoffs,
            "notes_checked": filed is not None, "most_built_on": None if filed is None else most_built_on(standings, filed),
            "ranked": [row(p) for p in standings.ranked], "baseline": [row(p) for p in standings.baseline],
            "unranked": [{"entry": dataclasses.asdict(u.entry), "pst_day": u.entry.pst_day, "reason": u.reason.name} for u in standings.unranked]}


def moment(text):
    return int(text) if text.isdigit() else utc(text)


def add_board_flags(parser):
    parser.add_argument("board_url")
    parser.add_argument("--cache", default="standings-cache.json", help="status cache file")
    parser.add_argument("--open", type=moment, default=WINDOW_OPEN, help="test window start, Unix seconds or ISO UTC")
    parser.add_argument("--close", type=moment, default=WINDOW_CLOSE, help="test window end, Unix seconds or ISO UTC")
    parser.add_argument("--early-open", type=moment, default=EARLY_EXACT_OPEN, help="test start of the early exact entries, Unix seconds or ISO UTC")


def add_note_flags(parser, required):
    parser.add_argument("--repo", required=required, help="a full, freshly pulled clone of the shared repository")
    parser.add_argument("--work", default=".", help="folder for unpacked circuits")
    parser.add_argument("--now", type=moment, default=None, help="test clock, Unix seconds or ISO UTC")


def rules_of(args):
    return Rules(window_open=args.open, window_close=args.close, early_exact_open=args.early_open)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_board_flags(parser)
    add_note_flags(parser, required=False)
    parser.add_argument("--json", help="also write the standings to this file")
    args = parser.parse_args()
    rules, reader = rules_of(args), Reader(args.board_url, args.cache)
    now = int(time.time()) if args.now is None else args.now
    try:
        board = read_board(reader)
        entries = to_entries(board, reader, rules)
        filed, clone = None, None
        if args.repo:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import notes
            clone = notes.describe_clone(args.repo)
            filed = notes.survey(args.repo, entries, reader, rules, args.work)
        standings = rank(entries, rules, now, filed)
    except BoardError as error:
        sys.exit(f"REFUSED: {error}")
    print(report(args.board_url, board, standings, filed, clone))
    if args.json:
        with open(args.json, "w") as sink:
            json.dump(jsonable(args.board_url, board, standings, reader, filed), sink, indent=1)


if __name__ == "__main__":
    sys.modules["standings"] = sys.modules["__main__"]  # audit.py and notes.py import this file by name
    main()
