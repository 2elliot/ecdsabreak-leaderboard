#!/usr/bin/env python3
"""Renders standings.py's JSON as one static page. Run: python3 -I build.py standings.json site/index.html"""
import datetime
import html
import json
import os
import re
import sys

REPO = "https://github.com/jtaroreh/ecdsafail-v2-reference"
CLOSE_WORDS = "Thursday 2026-11-12, 11:59 PM PST"
ENTRY_NAME = re.compile(r"comp-[A-Za-z0-9-]+-pr(\d+)-[0-9a-f]{12}")
REASONS = {
    "CANCELLED": "round cancelled",
    "OUTSIDE": "outside the window",
    "OVER_LIMIT": "over the daily limit",
    "WITHDRAWN": "withdrawn",
    "REJECTED": "refused, no test ran",
    "TIMED_OUT": "timed out",
    "INCOMPLETE": "no result yet",
    "FAILED": "failed testing",
    "NO_COST": "no cost on the board",
    "SAME_COST": "same costs as an earlier entry",
    "NO_NOTE": "no valid note",
}
HIDDEN_REASONS = {"BASELINE_FAILED", "PRACTICE"}
STYLE = """
:root{--bg:#fbfbfa;--fg:#1c1c1a;--muted:#6b6b66;--line:#e2e1dc;--card:#fff;--good:#1a7f4b;--accent:#2457c5}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ecebe6;--muted:#9a9a93;--line:#2e2e2b;--card:#1c1c1a;--good:#4cc38a;--accent:#8ab0ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:920px;margin:0 auto;padding:32px 16px 48px}
h1{font-size:24px;line-height:1.25;margin:0 0 4px}
h2{font-size:15px;margin:32px 0 10px}
p{margin:0}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.sub,.note,.when{color:var(--muted)}
.sub{margin-bottom:24px}
.note{font-size:13px;margin-top:10px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.label{color:var(--muted);font-size:13px}
.who{font-size:20px;font-weight:600;margin:2px 0}
.num{font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;white-space:nowrap}
th,td{padding:9px 10px;text-align:left;border-top:1px solid var(--line)}
thead th{border-top:0;color:var(--muted);font-size:13px;font-weight:500}
td.num,th.num{text-align:right}
.yes{color:var(--good);font-weight:600}
.empty{padding:14px 16px;color:var(--muted)}
"""
AGE_SCRIPT = """
const t=document.querySelector('time[data-age]');
if(t){const m=Math.round((Date.now()-Date.parse(t.dateTime))/60000);
t.textContent=m<1?'just now':m<60?m+' min ago':Math.round(m/6)/10+' hours ago';
if(m>30)t.textContent+=', so this page may be out of date';}
"""


def number(value):
    return "n/a" if value is None else f"{value:,}"


def beats(entry, line):
    t, qubit_time = entry["lowered_t"], entry["qubit_time"]
    return t <= line["lowered_t"] and qubit_time <= line["qubit_time"] and (t < line["lowered_t"] or qubit_time < line["qubit_time"])


def holder(ranked, line, cost):
    """The entry holding an award today: lowest cost among entries that beat the reference, and on a tie the earliest in board order."""
    rows = [row["entry"] for row in ranked if beats(row["entry"], line)]
    return min(rows, key=lambda e: (e[cost], e["round_id"], e["evaluation"]), default=None)


def percent(value, line):
    return f"{(value / line - 1) * 100:+.2f}%"


def entry_cell(entry):
    name = html.escape(entry["method"])
    found = ENTRY_NAME.fullmatch(entry["method"])
    return f'<a href="{REPO}/pull/{found.group(1)}">#{found.group(1)}</a>' if found else name


def award_card(title, entry, cost):
    if entry is None:
        body = '<p class="who">Nobody yet</p><p class="note">No entry beats the reference.</p>'
    else:
        body = f'<p class="who">{html.escape(entry["user"])}</p><p class="num">{number(entry[cost])}</p><p class="note">Entry {entry_cell(entry)}</p>'
    return f'<div class="card"><p class="label">{title}</p>{body}</div>'


def ranked_table(ranked, line):
    if not ranked:
        return '<div class="scroll"><p class="empty">No ranked entries yet.</p></div>'
    rows = []
    for row in ranked:
        e = row["entry"]
        rows.append(
            f'<tr><td class="num">{row["layer"]}</td><td>{html.escape(e["user"])}</td><td>{entry_cell(e)}</td>'
            f'<td class="num">{number(e["lowered_t"])}</td><td class="num">{percent(e["lowered_t"], line["lowered_t"])}</td>'
            f'<td class="num">{number(e["qubit_time"])}</td><td class="num">{percent(e["qubit_time"], line["qubit_time"])}</td>'
            f'<td>{"<span class=yes>Yes</span>" if beats(e, line) else "No"}</td></tr>'
        )
    head = '<tr><th class="num">Layer</th><th>Member</th><th>Entry</th><th class="num">T</th><th class="num">vs ref</th><th class="num">Qubit-time</th><th class="num">vs ref</th><th>Beats ref</th></tr>'
    return f'<div class="scroll"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def unranked_section(unranked):
    shown = [row for row in unranked if row["reason"] not in HIDDEN_REASONS]
    if not shown:
        return ""
    rows = []
    for row in shown:
        e = row["entry"]
        reason = REASONS.get(row["reason"], row["reason"].replace("_", " ").lower())
        rows.append(f'<tr><td>{html.escape(e["user"])}</td><td>{entry_cell(e)}</td><td>{html.escape(reason)}</td><td class="num">{number(e["boundary_failing"])}</td><td class="num">{number(e["f"])}</td></tr>')
    head = '<tr><th>Member</th><th>Entry</th><th>Why</th><th class="num">Boundary cases failed</th><th class="num">Inputs failed</th></tr>'
    return f'<h2>Listed, not ranked</h2><div class="scroll"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def page(data, now):
    line = data["baseline"][0]["entry"]
    ranked = sorted(data["ranked"], key=lambda r: (r["layer"], r["entry"]["qubit_time"], r["entry"]["round_id"], r["entry"]["evaluation"]))
    state = {"before": "Not open yet", "open": "Open", "closed": "Closed"}.get(data["phase"], data["phase"])
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300"><title>Circuit competition</title><style>{STYLE}</style></head><body><main>
<h1>Circuit competition</h1>
<p class="sub">{html.escape(state)}. Closes {CLOSE_WORDS}. Updated <time class="when" data-age datetime="{stamp}">{stamp}</time>.</p>
<div class="cards">{award_card("Holding Lowest T", holder(ranked, line, "lowered_t"), "lowered_t")}{award_card("Holding Lowest qubit-time", holder(ranked, line, "qubit_time"), "qubit_time")}</div>
<p class="note">Nothing is final until the audit after the close, which can drop an entry.</p>
<h2>Line to beat</h2>
<p class="num">The reference: T {number(line["lowered_t"])}, qubit-time {number(line["qubit_time"])}. To beat it, an entry must be lower on one cost and no higher on the other.</p>
<h2>Standings</h2>
{ranked_table(ranked, line)}
{unranked_section(data["unranked"])}
<p class="note">Sampled and unqualified: one controlled addition, not an attack. Read from <a href="{html.escape(data["url"])}/v2/tested">the public board</a> by <a href="https://github.com/jtaroreh/ecdsabreak-leaderboard/blob/main/standings.py">standings.py</a>. Notes aren't checked here, so the operator's final table decides. Enter at <a href="{REPO}">the reference repository</a>.</p>
</main><script>{AGE_SCRIPT}</script></body></html>
"""


def main(source, target):
    with open(source) as f:
        data = json.load(f)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as f:
        f.write(page(data, datetime.datetime.now(datetime.timezone.utc)))


if __name__ == "__main__":
    main(*sys.argv[1:])
