#!/usr/bin/env python3
"""
Build encrypted NAMES 2026 scoreboard HTML from Salesforce data.

Usage:
    python3 build.py <input_data.json> <output.html>

Input JSON format:
{
  "password": "names2026",
  "golden_target": "TBD",
  "opps": [
    {"owner": "Lucas Goldman", "stage": "0 - Discovery", "account": "Alcon", "arr": null}
  ]
}
"""

import os
import sys
import json
import base64
import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


# Player/team configuration
PLAYERS = {
    "Lucas Goldman":         {"team": "REPS",  "short": "Lucas"},
    "Haolynn Lu":            {"team": "REPS",  "short": "Haolynn"},
    "Charles Lawson":        {"team": "STRAT", "short": "Charles"},
    "Lauren Dunford":        {"team": "STRAT", "short": "Lauren"},
    "Charlotte Ward Brodey": {"team": "STRAT", "short": "Charlotte"},
}


def encrypt_aesgcm(password: str, plaintext: str) -> str:
    """Encrypt plaintext with AES-GCM using password-derived key. Returns base64."""
    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = kdf.derive(password.encode("utf-8"))
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    package = salt + iv + ciphertext
    return base64.b64encode(package).decode("ascii")


def categorize_opp(stage: str) -> str:
    """Return 'T' (trial), 'M-live' (live meeting), 'M-pre' (pre-booked), or 'L' (lead)."""
    s = (stage or "").lower()
    if "trial" in s or "poc" in s:
        return "T"
    if any(k in s for k in ["demo", "qualify", "proposal", "negotiation",
                             "1 -", "2 -", "3 -", "4 -", "5 -", "closed"]):
        return "M-live"
    if "lead" in s:
        return "L"
    return "M-pre"


def points_for(category: str) -> int:
    return {"L": 1, "M-pre": 2, "M-live": 5, "T": 20}.get(category, 0)


def format_money(amount: float) -> str:
    """Format dollar amount as $X, $1.2K, $45K, $1.2M, etc."""
    if amount is None or amount == 0:
        return "$0"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M".replace(".0M", "M")
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:.0f}"


def compute_player_scores(opps: list, golden_target: str):
    """Compute per-player scores, pipeline, breakdown. Applies 3x golden target multiplier."""
    golden = (golden_target or "").strip().lower()
    apply_golden = golden and golden != "tbd"

    scores = {}
    for name in PLAYERS:
        scores[name] = {
            "pts": 0, "pipeline": 0.0, "opps": 0,
            "L": 0, "M": 0, "T": 0,
        }

    for opp in opps:
        owner = opp.get("owner", "")
        if owner not in PLAYERS:
            continue
        cat = categorize_opp(opp.get("stage", ""))
        base_pts = points_for(cat)
        arr = opp.get("arr") or 0
        account = (opp.get("account") or "").lower()

        multiplier = 3 if (apply_golden and account == golden) else 1
        pts = base_pts * multiplier

        s = scores[owner]
        s["pts"] += pts
        s["pipeline"] += arr
        s["opps"] += 1
        if cat == "L":
            s["L"] += 1
        elif cat == "T":
            s["T"] += 1
        else:
            s["M"] += 1

    return scores


def build_standings_row(rank_label: str, player_short: str, player_full: str,
                         team: str, momentum: str, L: int, M: int, T: int,
                         pipeline: float, pts: int, is_zero: bool = False,
                         rank_class: str = "") -> str:
    tag_class = "tag-reps" if team == "REPS" else "tag-strat"
    zero_class = " zero" if is_zero else ""

    if rank_class:
        tr_class = f'class="{rank_class}{zero_class}"'
    elif zero_class:
        tr_class = f'class="{zero_class.strip()}"'
    else:
        tr_class = ""

    if rank_label in ("🥇", "🥈", "🥉"):
        rank_cell = f'<span class="medal">{rank_label}</span>'
    elif rank_label == "—":
        rank_cell = '<span class="dash">—</span>'
    else:
        rank_cell = rank_label

    pipeline_class = "pipeline-cell"
    if pipeline == 0:
        pipeline_class += " zero"
    pipeline_cell = f'<span>{format_money(pipeline)}</span>'

    return f'''        <tr {tr_class}>
          <td class="rank-cell">{rank_cell}</td>
          <td class="player-cell"><span class="name">{player_full}</span><span class="tag {tag_class}">{team}</span></td>
          <td class="fire-cell">{momentum}</td>
          <td class="breakdown-cell">L <b>{L}</b> · M <b>{M}</b> · T <b>{T}</b></td>
          <td class="num {pipeline_class}">{pipeline_cell}</td>
          <td class="num pts-cell">{pts}</td>
        </tr>
'''


def build_ticker(scores: dict, golden_target: str, total_pipeline: float) -> str:
    """Build ticker items string (one copy — template duplicates for seamless loop)."""
    # Sort players for hype
    sorted_players = sorted(scores.items(), key=lambda x: -x[1]["pts"])
    top = sorted_players[0]
    top_name = PLAYERS[top[0]]["short"]
    top_pts = top[1]["pts"]

    reps_total = sum(s["pts"] for p, s in scores.items() if PLAYERS[p]["team"] == "REPS")
    strat_total = sum(s["pts"] for p, s in scores.items() if PLAYERS[p]["team"] == "STRAT")

    items = []
    if strat_total == 0 and reps_total > 0:
        items.append(f'<span class="item"><span class="t-gold">● TIP-OFF</span>&nbsp;&nbsp;{top_name} leads all players with {top_pts} pts — Strat team yet to score</span>')
    else:
        gap = abs(reps_total - strat_total)
        leader = "REPS" if reps_total >= strat_total else "STRAT"
        items.append(f'<span class="item"><span class="t-gold">● LEADING</span>&nbsp;&nbsp;Team {leader} up by {gap} pts — floor action heating up</span>')

    items.append(f'<span class="item"><span class="t-light-eggplant">● ON FIRE</span>&nbsp;&nbsp;{top_name} owns pole position with {scores[top[0]]["opps"]} NAMES opps locked in</span>')
    items.append(f'<span class="item"><span class="t-light-blue">● UNDERDOG</span>&nbsp;&nbsp;Strat needs to work the floor — every meeting counts 5 pts, every trial 20</span>')

    if total_pipeline > 0:
        items.append(f'<span class="item"><span class="t-gold">● PIPELINE</span>&nbsp;&nbsp;{format_money(total_pipeline)} on the board · add ARR to your opps to join the ranks</span>')
    else:
        items.append('<span class="item"><span class="t-gold">● PRO TIP</span>&nbsp;&nbsp;Add ARR to your NAMES opps in Salesforce — pipeline $ shows up here next refresh</span>')

    items.append('<span class="item"><span class="t-light-eggplant">● HYPE</span>&nbsp;&nbsp;First trial on the floor = champagne + belt photo op 🏆</span>')

    if (golden_target or "").strip().lower() in ("", "tbd"):
        items.append('<span class="item"><span class="t-gold">● GOLDEN TARGET</span>&nbsp;&nbsp;3x multiplier unlocks — pick is TBD, stay tuned</span>')
    else:
        items.append(f'<span class="item"><span class="t-gold">● GOLDEN TARGET</span>&nbsp;&nbsp;{golden_target} = 3x multiplier — book that meeting before anyone else</span>')

    items.append('<span class="item"><span class="t-light-blue">● FLOOR NOTE</span>&nbsp;&nbsp;Every booth convo matters · log it, book it, win it</span>')

    return "\n        ".join(items)


def build_scoreboard_html(template_path: Path, data: dict) -> str:
    """Build the full scoreboard HTML from template + data."""
    template = template_path.read_text()

    opps = data.get("opps", [])
    golden_target = data.get("golden_target", "TBD")

    scores = compute_player_scores(opps, golden_target)

    # Team totals
    reps_pts_total = sum(s["pts"] for p, s in scores.items() if PLAYERS[p]["team"] == "REPS")
    strat_pts_total = sum(s["pts"] for p, s in scores.items() if PLAYERS[p]["team"] == "STRAT")
    reps_pipeline = sum(s["pipeline"] for p, s in scores.items() if PLAYERS[p]["team"] == "REPS")
    strat_pipeline = sum(s["pipeline"] for p, s in scores.items() if PLAYERS[p]["team"] == "STRAT")
    reps_opps = sum(s["opps"] for p, s in scores.items() if PLAYERS[p]["team"] == "REPS")
    strat_opps = sum(s["opps"] for p, s in scores.items() if PLAYERS[p]["team"] == "STRAT")

    reps_avg = reps_pts_total // 2 if reps_pts_total else 0
    strat_avg = strat_pts_total // 3 if strat_pts_total else 0

    # Who's leading
    if reps_avg == strat_avg:
        reps_status, strat_status = "TIED", "TIED"
        reps_status_class = strat_status_class = ""
        reps_emoji = strat_emoji = "⚔️"
        hype_tag = "DEADLOCKED"
        hype_text = f"Tied at {reps_avg} avg pts — dogfight mode engaged"
    elif reps_avg > strat_avg:
        reps_status, strat_status = "🔥 LEADING", "CHASING"
        reps_status_class = "lead"
        strat_status_class = ""
        reps_emoji, strat_emoji = "👑", "🎯"
        gap = reps_pts_total - strat_pts_total
        if strat_pts_total == 0:
            hype_tag = "TIP-OFF"
            hype_text = f"Reps up {reps_pts_total}–0 on pre-booked pipeline · Strat needs floor hustle to flip the script"
        else:
            hype_tag = "REPS LEADING"
            hype_text = f"Reps up by {gap} pts · Strat clawing back — anything can happen"
    else:
        reps_status, strat_status = "CHASING", "🔥 LEADING"
        reps_status_class = ""
        strat_status_class = "lead"
        reps_emoji, strat_emoji = "🎯", "👑"
        gap = strat_pts_total - reps_pts_total
        hype_tag = "STRAT SURGES"
        hype_text = f"Strat flips the script · up by {gap} pts · Reps need to answer"

    # Bounce animation on the leader
    reps_bounce = "bounce" if reps_avg > strat_avg else ""
    strat_bounce = "bounce" if strat_avg > reps_avg else ""

    # Rank players for standings table
    ranked = sorted(scores.items(), key=lambda x: (-x[1]["pts"], -x[1]["T"], -x[1]["M"], x[0]))

    standings_rows = []
    rank_counter = 1
    for full_name, s in ranked:
        team = PLAYERS[full_name]["team"]
        is_zero = s["pts"] == 0
        if is_zero:
            rank_label = "—"
            rank_class = ""
            momentum = '<span style="color: var(--gray-blue);">Fresh start — hit the floor</span>'
        else:
            if rank_counter == 1:
                rank_label, rank_class = "🥇", "rank-1"
                momentum = '<span class="fire">🔥</span> On fire'
            elif rank_counter == 2:
                rank_label, rank_class = "🥈", "rank-2"
                momentum = "💪 In striking distance"
            elif rank_counter == 3:
                rank_label, rank_class = "🥉", "rank-3"
                momentum = "📈 Climbing the board"
            else:
                rank_label, rank_class = str(rank_counter), ""
                momentum = "⚡ Working the floor"
            rank_counter += 1

        row = build_standings_row(
            rank_label=rank_label,
            player_short=PLAYERS[full_name]["short"],
            player_full=full_name,
            team=team,
            momentum=momentum,
            L=s["L"], M=s["M"], T=s["T"],
            pipeline=s["pipeline"],
            pts=s["pts"],
            is_zero=is_zero,
            rank_class=rank_class,
        )
        standings_rows.append(row)

    # Pipeline leader banner text
    total_pipeline = reps_pipeline + strat_pipeline
    total_opps = reps_opps + strat_opps
    if total_pipeline == 0:
        pipeline_leader_text = "No ARR logged yet — add $ to your opps to light up the board"
    else:
        top_pipeline_player = max(scores.items(), key=lambda x: x[1]["pipeline"])
        pipeline_leader_text = f"{PLAYERS[top_pipeline_player[0]]['short']} leading pipeline with {format_money(top_pipeline_player[1]['pipeline'])}"

    # Golden target display
    golden_display = "TBD — pick by 9am" if (golden_target or "").lower() in ("", "tbd") else golden_target

    # Ticker
    ticker_items = build_ticker(scores, golden_target, total_pipeline)

    # Last refresh timestamp (Pacific)
    now_pt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-7)))
    last_refresh = now_pt.strftime("%b %-d · %-I:%M%p PT").lower().replace("pm pt", " PM PT").replace("am pt", " AM PT")

    # Substitutions
    replacements = {
        "{{HYPE_TAG}}": hype_tag,
        "{{HYPE_TEXT}}": hype_text,
        "{{REPS_EMOJI}}": reps_emoji,
        "{{REPS_STATUS}}": reps_status,
        "{{REPS_STATUS_CLASS}}": reps_status_class,
        "{{REPS_AVG}}": str(reps_avg),
        "{{REPS_BOUNCE}}": reps_bounce,
        "{{REPS_PIPELINE}}": format_money(reps_pipeline),
        "{{REPS_OPPS}}": str(reps_opps),
        "{{STRAT_EMOJI}}": strat_emoji,
        "{{STRAT_STATUS}}": strat_status,
        "{{STRAT_STATUS_CLASS}}": strat_status_class,
        "{{STRAT_AVG}}": str(strat_avg),
        "{{STRAT_BOUNCE}}": strat_bounce,
        "{{STRAT_PIPELINE}}": format_money(strat_pipeline),
        "{{STRAT_OPPS}}": str(strat_opps),
        "{{TOTAL_PIPELINE}}": format_money(total_pipeline),
        "{{TOTAL_OPPS}}": str(total_opps),
        "{{PIPELINE_LEADER_TEXT}}": pipeline_leader_text,
        "{{TICKER_ITEMS}}": ticker_items,
        "{{STANDINGS_ROWS}}": "".join(standings_rows),
        "{{GOLDEN_TARGET}}": golden_display,
        "{{LAST_REFRESH}}": last_refresh,
    }

    for key, val in replacements.items():
        template = template.replace(key, val)

    return template


def build_wrapped_html(wrapper_path: Path, encrypted_b64: str) -> str:
    wrapper = wrapper_path.read_text()
    return wrapper.replace("{{ENCRYPTED_BLOB}}", encrypted_b64)


def main():
    if len(sys.argv) < 3:
        print("Usage: build.py <input.json> <output.html>", file=sys.stderr)
        sys.exit(1)

    input_json_path = Path(sys.argv[1])
    output_html_path = Path(sys.argv[2])

    data = json.loads(input_json_path.read_text())
    password = data.get("password", "")
    if not password:
        print("ERROR: password missing in input JSON", file=sys.stderr)
        sys.exit(1)

    script_dir = Path(__file__).parent
    scoreboard_template = script_dir / "scoreboard-template.html"
    wrapper_template = script_dir / "wrapper-template.html"

    # Build scoreboard HTML
    scoreboard_html = build_scoreboard_html(scoreboard_template, data)

    # Encrypt it
    encrypted_b64 = encrypt_aesgcm(password, scoreboard_html)

    # Wrap it
    final_html = build_wrapped_html(wrapper_template, encrypted_b64)

    # Write output
    output_html_path.write_text(final_html)
    print(f"✓ Built {output_html_path} ({output_html_path.stat().st_size} bytes)")
    print(f"  Scoreboard: {len(scoreboard_html)} bytes")
    print(f"  Encrypted:  {len(encrypted_b64)} bytes (base64)")


if __name__ == "__main__":
    main()
