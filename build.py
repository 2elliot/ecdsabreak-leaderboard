#!/usr/bin/env python3
"""Renders standings.py's JSON as one static page. Run: python3 -I build.py standings.json site/index.html"""
import datetime
import html
import json
import math
import os
import re
import shutil
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
.note.lede{margin:0 0 10px}
.note{font-size:13px;margin-top:10px}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:24px}
.top .sub{margin-bottom:0}
.brand{flex-shrink:0}
.brand img{height:36px;width:auto;display:block;filter:brightness(0);opacity:0.9}
a.brand{text-decoration:none}
a.brand:hover{opacity:0.7}
@media (prefers-color-scheme:dark){.brand img{filter:none;opacity:0.95}}
.split{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,400px),1fr));gap:12px;align-items:start}
.split th,.split td{padding:9px 7px}
.split h3{font-size:13px;font-weight:500;color:var(--muted);margin:0 0 6px}
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
:root{--frontier:#2457c5;--ref:#c2570c}
@media (prefers-color-scheme:dark){:root{--frontier:#6690ee;--ref:#cc6f1c}}
.chart{position:relative;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 8px 4px}
.chart .plot{overflow-x:auto;padding-bottom:6px}
.chart .plot svg{display:block;width:100%;min-width:520px;height:auto;font-size:13px;font-variant-numeric:tabular-nums}
.chart .grid{stroke:var(--line);stroke-dasharray:3 4}
.chart .tick{fill:var(--muted)}
.chart .axis{fill:var(--muted);font-size:14px}
.chart .zone{fill:var(--good);fill-opacity:.06}
.chart .zone-label{fill:var(--good);font-size:13px}
.chart .step{fill:none;stroke:var(--frontier);stroke-width:2;stroke-linejoin:round}
.chart .pt{cursor:default;outline:none}
.chart .pt .hit{fill:transparent}
.chart .pt .dot{stroke:var(--card);stroke-width:2}
.chart .pt.front .dot{fill:var(--frontier)}
.chart .pt.back .dot{fill:var(--card);stroke:var(--muted);stroke-width:1.5}
.chart .pt.ref .dot{fill:var(--ref)}
.chart .pt:hover .dot,.chart .pt:focus .dot{stroke:var(--fg);stroke-width:2}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;margin:6px 8px 4px;color:var(--muted);font-size:13px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend svg{width:16px;height:12px;flex-shrink:0}
.tip{position:absolute;pointer-events:none;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:13px;line-height:1.4;box-shadow:0 4px 14px rgba(0,0,0,.12);white-space:nowrap}
.tip[hidden]{display:none}
.tip b{display:block}
.tip span{color:var(--muted)}
.tip div+div{margin-top:6px;padding-top:6px;border-top:1px solid var(--line)}
"""
AGE_SCRIPT = """
const t=document.querySelector('time[data-age]');
if(t){const m=Math.round((Date.now()-Date.parse(t.dateTime))/60000);
t.textContent=m<1?'just now':m<60?m+' min ago':Math.round(m/6)/10+' hours ago';
if(m>30)t.textContent+=', so this page may be out of date';}
const chart=document.querySelector('.chart');
if(chart){const tip=chart.querySelector('.tip'),hide=()=>{tip.hidden=true};
const show=g=>{tip.replaceChildren();
for(const p of JSON.parse(g.dataset.tip)){const d=document.createElement('div');
for(const v of [p.t,p.qt]){const b=document.createElement('b');b.textContent=v;d.append(b);}
const s=document.createElement('span');s.textContent=p.who;d.append(s);tip.append(d);}
tip.hidden=false;const c=chart.getBoundingClientRect(),r=g.querySelector('.dot').getBoundingClientRect();
let x=r.right-c.left+10,y=r.top-c.top-tip.offsetHeight-6;
if(x+tip.offsetWidth>c.width)x=r.left-c.left-tip.offsetWidth-10;
if(y<0)y=r.bottom-c.top+6;
tip.style.left=Math.max(0,x)+'px';tip.style.top=y+'px';};
for(const g of chart.querySelectorAll('.pt')){g.addEventListener('pointerenter',()=>show(g));g.addEventListener('focus',()=>show(g));
g.addEventListener('pointerleave',hide);g.addEventListener('blur',hide);}
chart.querySelector('.plot').addEventListener('scroll',hide);}
"""
CHART = {"width": 888, "height": 400, "left": 64, "right": 32, "top": 20, "bottom": 50}
TICK_STEPS = ((1,), (1, 2, 5), (1, 1.5, 2, 3, 4, 5, 6, 8), (1, 1.2, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6, 7, 8, 9))
OVERLAP_PX = 7


def number(value):
    return "n/a" if value is None else f"{value:,}"


def beats(entry, line):
    t, qubit_time = entry["lowered_t"], entry["qubit_time"]
    return t <= line["lowered_t"] and qubit_time <= line["qubit_time"] and (t < line["lowered_t"] or qubit_time < line["qubit_time"])


OTHER = {"lowered_t": "qubit_time", "qubit_time": "lowered_t"}


def ranking(cost):
    """standings.py's `ranked_by`: the lower `cost`, then the lower other cost, then the earlier in board order."""
    return lambda e: (e[cost], e[OTHER[cost]], e["round_id"], e["evaluation"])


def holder(ranked, line, cost):
    """The entry holding an award today: first by `ranking(cost)` among entries that beat the reference."""
    return min((row["entry"] for row in ranked if beats(row["entry"], line)), key=ranking(cost), default=None)


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


def ranked_table(ranked, line, cost, title):
    if not ranked:
        return f'<div><h3>{title}</h3><div class="scroll"><p class="empty">No ranked entries yet.</p></div></div>'
    rows = []
    for place, e in enumerate(sorted((row["entry"] for row in ranked), key=ranking(cost)), 1):
        rows.append(
            f'<tr><td class="num">{place}</td><td>{html.escape(e["user"])}</td><td>{entry_cell(e)}</td>'
            f'<td class="num">{number(e[cost])}</td><td class="num">{percent(e[cost], line[cost])}</td>'
            f'<td>{"<span class=yes>Yes</span>" if beats(e, line) else "No"}</td></tr>'
        )
    head = f'<tr><th class="num">#</th><th>Member</th><th>Entry</th><th class="num">{title.removeprefix("By ")}</th><th class="num">vs ref</th><th>Beats ref</th></tr>'
    return f'<div><h3>{title}</h3><div class="scroll"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div></div>'


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


def compact(value):
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= size:
            return f"{value / size:.3g}{unit}"
    return f"{value:g}"


def log_ticks(low, high):
    """Round values between `low` and `high`, from the coarsest step set that gives at least four."""
    decades = range(math.floor(math.log10(low)), math.ceil(math.log10(high)) + 1)
    for steps in TICK_STEPS:
        ticks = [m * 10**d for d in decades for m in steps if low <= m * 10**d <= high]
        if len(ticks) >= 4:
            break
    return ticks[:: -(-len(ticks) // 8)]


def log_scale(values, start, end):
    """A log scale over `values`, padded 6% each side, mapping onto pixels `start`..`end`."""
    low, high = math.log10(min(values)), math.log10(max(values))
    pad = max(high - low, 0.1) * 0.06
    low, high = low - pad, high + pad
    return (lambda v: start + (math.log10(v) - low) / (high - low) * (end - start)), 10**low, 10**high


def entry_label(entry):
    found = ENTRY_NAME.fullmatch(entry["method"])
    return f'{entry["user"]} · entry #{found.group(1)}' if found else f'{entry["user"]} · {entry["method"]}'


def frontier_path(front, x, y, top, right):
    """The staircase along the frontier: everything up and to the right of it is beaten by some entry on it."""
    points = sorted(front, key=lambda e: (e["qubit_time"], e["lowered_t"]))
    path = [f'M{x(points[0]["qubit_time"]):.1f},{top}', f'V{y(points[0]["lowered_t"]):.1f}']
    for e in points[1:]:
        path += [f'H{x(e["qubit_time"]):.1f}', f'V{y(e["lowered_t"]):.1f}']
    path.append(f"H{right}")
    return "".join(path)


def frontier_chart(ranked, line):
    """T against qubit-time on log scales: the frontier, every other ranked entry, and the reference."""
    w, h = CHART["width"], CHART["height"]
    left, right, top, bottom = CHART["left"], w - CHART["right"], CHART["top"], h - CHART["bottom"]
    entries = [row["entry"] for row in ranked]
    x, x_low, x_high = log_scale([e["qubit_time"] for e in [*entries, line]], left, right)
    y, y_low, y_high = log_scale([e["lowered_t"] for e in [*entries, line]], bottom, top)

    parts = []
    for v in log_ticks(x_low, x_high):
        parts.append(f'<line class="grid" x1="{x(v):.1f}" x2="{x(v):.1f}" y1="{top}" y2="{bottom}"/><text class="tick" x="{x(v):.1f}" y="{bottom + 18}" text-anchor="middle">{compact(v)}</text>')
    for v in log_ticks(y_low, y_high):
        parts.append(f'<line class="grid" x1="{left}" x2="{right}" y1="{y(v):.1f}" y2="{y(v):.1f}"/><text class="tick" x="{left - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{compact(v)}</text>')
    parts.append(f'<text class="axis" x="{(left + right) / 2}" y="{h - 6}" text-anchor="middle">qubit-time (log scale)</text>')
    parts.append(f'<text class="axis" transform="rotate(-90)" x="{-(top + bottom) / 2}" y="14" text-anchor="middle">T (log scale)</text>')
    parts.append(f'<rect class="zone" x="{left}" y="{y(line["lowered_t"]):.1f}" width="{x(line["qubit_time"]) - left:.1f}" height="{bottom - y(line["lowered_t"]):.1f}"/>')
    parts.append(f'<text class="zone-label" x="{left + 8}" y="{bottom - 8}">Beats the reference</text>')
    front = [row["entry"] for row in ranked if row["layer"] == 1]
    if front:
        parts.append(f'<path class="step" d="{frontier_path(front, x, y, top, right)}"/>')

    marks = [("back", e) for e in entries if not any(e is f for f in front)] + [("front", e) for e in front] + [("ref", line)]
    clusters = []
    for kind, e in marks:
        at = (x(e["qubit_time"]), y(e["lowered_t"]))
        near = next((c for c in clusters if math.dist(c["at"], at) < OVERLAP_PX), None)
        if near is None:
            clusters.append({"at": at, "kind": kind, "entries": [e]})
        else:
            near["kind"], near["entries"] = kind, [e, *near["entries"]]
    for c in clusters:
        cx, cy = c["at"]
        dot = f'<path class="dot" d="M{cx:.1f},{cy - 7:.1f}l7,7l-7,7l-7,-7z"/>' if c["kind"] == "ref" else f'<circle class="dot" cx="{cx:.1f}" cy="{cy:.1f}" r="5"/>'
        tip = [{"t": f'T {number(e["lowered_t"])}', "qt": f'qubit-time {number(e["qubit_time"])}', "who": "Reference" if e is line else entry_label(e)} for e in c["entries"]]
        said = "; ".join(f'{p["who"]}: {p["t"]}, {p["qt"]}' for p in tip)
        parts.append(f'<g class="pt {c["kind"]}" tabindex="0" role="img" aria-label="{html.escape(said)}" data-tip="{html.escape(json.dumps(tip))}"><circle class="hit" cx="{cx:.1f}" cy="{cy:.1f}" r="12"/>{dot}</g>')

    legend = (
        '<span><svg viewBox="0 0 16 12"><path d="M0 2H8V10H16" fill="none" stroke="var(--frontier)" stroke-width="2"/></svg>Frontier</span>'
        '<span><svg viewBox="0 0 16 12"><circle cx="8" cy="6" r="5" fill="var(--frontier)"/></svg>On the frontier</span>'
        '<span><svg viewBox="0 0 16 12"><circle cx="8" cy="6" r="4.5" fill="none" stroke="var(--muted)" stroke-width="1.5"/></svg>Other ranked entry</span>'
        '<span><svg viewBox="0 0 16 12"><path d="M8 0l6 6l-6 6l-6-6z" fill="var(--ref)"/></svg>Reference</span>'
    )
    svg = f'<svg viewBox="0 0 {w} {h}" role="group" aria-label="Ranked entries by T and qubit-time">{"".join(parts)}</svg>'
    return f'<div class="chart"><div class="plot">{svg}</div><div class="legend">{legend}</div><div class="tip" hidden></div></div>'


def page(data, now):
    line = data["baseline"][0]["entry"]
    ranked = data["ranked"]
    state = {"before": "Not open yet", "open": "Open", "closed": "Closed"}.get(data["phase"], data["phase"])
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300"><title>Circuit competition</title><style>{STYLE}</style></head><body><main>
<div class="top">
<div>
<h1>Circuit competition</h1>
<p class="sub">{html.escape(state)}. Closes {CLOSE_WORDS}. Updated <time class="when" data-age datetime="{stamp}">{stamp}</time>.</p>
</div>
<a href="https://qcb.berkeley.edu" class="brand" aria-label="Quantum Computing at Berkeley"><img src="logo.png" alt="Quantum Computing at Berkeley"></a>
</div>
<div class="cards">{award_card("Holding Lowest T", holder(ranked, line, "lowered_t"), "lowered_t")}{award_card("Holding Lowest qubit-time", holder(ranked, line, "qubit_time"), "qubit_time")}</div>
<p class="note">Nothing is final until the audit after the close, which can drop an entry.</p>
<h2>Line to beat</h2>
<p class="num">The reference: T {number(line["lowered_t"])}, qubit-time {number(line["qubit_time"])}. To beat it, an entry must be lower on one cost and no higher on the other.</p>
<h2>Frontier</h2>
<p class="note lede">Lower and further left is better. The line joins the entries that no other entry beats on both costs.</p>
{frontier_chart(ranked, line)}
<h2>Standings</h2>
<div class="split">{ranked_table(ranked, line, "lowered_t", "By T")}{ranked_table(ranked, line, "qubit_time", "By qubit-time")}</div>
{unranked_section(data["unranked"])}
<p class="note">Sampled and unqualified: one controlled addition, not an attack. Read from <a href="{html.escape(data["url"])}/v2/tested">the public board</a> by <a href="https://github.com/jtaroreh/ecdsabreak-leaderboard/blob/main/standings.py">standings.py</a>. Notes aren't checked here, so the operator's final table decides. Enter at <a href="{REPO}">the reference repository</a>.</p>
</main><script>{AGE_SCRIPT}</script></body></html>
"""


def main(source, target):
    with open(source) as f:
        data = json.load(f)
    target_dir = os.path.dirname(target)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)
    repo_logo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
    if os.path.exists(repo_logo):
        shutil.copy2(repo_logo, os.path.join(target_dir or ".", "logo.png"))
    with open(target, "w") as f:
        f.write(page(data, datetime.datetime.now(datetime.timezone.utc)))


if __name__ == "__main__":
    main(*sys.argv[1:])
