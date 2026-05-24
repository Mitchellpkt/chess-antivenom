"""Standalone JSON-to-HTML report converter for antivenom results.

Takes the dict produced by ``AntivenomResult.to_json_dict()`` and returns a
self-contained HTML document — embedded CSS, embedded ``chess.svg`` board
diagrams for the top solutions, no external dependencies, no JavaScript.
Foldability is provided by native HTML5 ``<details>/<summary>``.

The converter is a pure function on the JSON dict, so it can be tested
without running a full antivenom search — feed it any dict that matches the
schema and assert on the returned string.
"""

from __future__ import annotations

import base64
import statistics
from collections import defaultdict
from html import escape
from typing import Any
from urllib.parse import quote

import chess
import chess.svg
from loguru import logger


# Tiny chess-knight favicon, embedded as a data URI so the report stays
# self-contained. Cream knight on a warm-brown rounded square — same palette
# as the rest of the report.
_FAVICON_SVG: bytes = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    b'<rect width="100" height="100" rx="16" fill="#8d6e63"/>'
    b'<text x="50" y="78" font-size="78" text-anchor="middle" '
    b'fill="#f5ede0" font-family="Georgia, serif">'
    b'\xe2\x99\x9e</text>'  # U+265E BLACK CHESS KNIGHT
    b'</svg>'
)
_FAVICON_DATA_URI: str = (
    "data:image/svg+xml;base64," + base64.b64encode(_FAVICON_SVG).decode("ascii")
)


# Tan / brown palette. Cream background, warm browns for text and chrome.
_CSS: str = """
:root {
  --bg: #f5ede0;
  --card: #ede0c8;
  --card-alt: #e3d4b6;
  --text: #3e2723;
  --text-soft: #6d4c41;
  --accent: #8d6e63;
  --border: #a1887f;
  --gold: #d7b079;
  --gold-strong: #b6864a;
  --bad: #6e4838;
  --shadow: rgba(62, 39, 35, 0.12);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 14px;
  line-height: 1.45;
}
main {
  max-width: 1100px;
  margin: 0 auto;
  padding: 24px;
}
header.report-header {
  background: var(--accent);
  color: #fdf6e9;
  padding: 24px 28px;
  border-radius: 8px;
  box-shadow: 0 2px 6px var(--shadow);
  margin-bottom: 24px;
}
header.report-header .byline {
  font-size: 11px;
  opacity: 0.78;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin: 0 0 10px;
  font-weight: 500;
}
header.report-header .byline a {
  color: inherit;
  text-decoration: none;
  border-bottom: 1px dotted rgba(253, 246, 233, 0.4);
}
header.report-header .byline a:hover { border-bottom-color: rgba(253, 246, 233, 0.9); }
header.report-header h1 {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 600;
}
header.report-header .subtitle {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  opacity: 0.92;
}
header.report-header .quickstats {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  font-size: 13px;
}
header.report-header .quickstats span strong {
  display: block;
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 2px;
}
details {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 16px;
  padding: 0;
  box-shadow: 0 1px 2px var(--shadow);
}
details > summary {
  cursor: pointer;
  padding: 12px 16px;
  font-weight: 600;
  font-size: 15px;
  color: var(--text);
  list-style: none;
  user-select: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--card-alt);
  border-radius: 6px 6px 0 0;
}
details[open] > summary { border-bottom: 1px solid var(--border); }
details > summary::after {
  content: "▸";
  font-size: 12px;
  color: var(--text-soft);
  transition: transform 120ms;
}
details[open] > summary::after { content: "▾"; }
details > .body { padding: 14px 18px; }
table {
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
}
th, td {
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
}
th {
  background: var(--card-alt);
  font-weight: 600;
  color: var(--text);
}
tr:hover td { background: rgba(141, 110, 99, 0.08); }
.kv {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 18px;
  font-size: 13px;
}
.kv dt { color: var(--text-soft); font-weight: 600; }
.kv dd { margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.eval { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 600; }
.eval-wp-best { color: #5b3a17; background: var(--gold); padding: 1px 6px; border-radius: 3px; }
.eval-wp-good { color: #4f3520; }
.eval-even { color: var(--text-soft); }
.eval-wp-bad { color: var(--bad); }
.eval-terminal-win { color: #4a2f10; background: var(--gold); padding: 1px 6px; border-radius: 3px; font-weight: 700; }
.eval-terminal-loss { color: #fdf6e9; background: var(--bad); padding: 1px 6px; border-radius: 3px; }
.eval-terminal-draw { color: var(--text-soft); font-style: italic; }
.bar-row { display: grid; grid-template-columns: 220px 60px 1fr; gap: 10px; align-items: center; padding: 3px 0; }
.bar-row .label { font-size: 12px; color: var(--text-soft); }
.bar-row .count { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; text-align: right; color: var(--text); }
.bar-row .bar { background: var(--gold); height: 14px; border-radius: 2px; }
.bar-row.is-bad .bar { background: var(--bad); }
.bar-row.is-even .bar { background: var(--accent); }
.solution {
  border: 1px solid var(--border);
  background: var(--card);
  border-radius: 6px;
  padding: 12px 16px;
  margin-bottom: 10px;
}
.solution.solution-top { background: linear-gradient(180deg, #f0e1c1, var(--card)); }
.solution .head { display: flex; gap: 16px; align-items: baseline; flex-wrap: wrap; }
.solution .rank { font-weight: 700; color: var(--text-soft); min-width: 40px; }
.solution .line { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 14px; flex: 1; }
.solution .board-row { display: flex; gap: 18px; align-items: flex-start; margin-top: 10px; }
.solution .board-row svg { background: #fdf6e9; border: 1px solid var(--border); border-radius: 4px; }
.solution .meta-block { font-size: 12px; flex: 1; }
.solution .meta-block .kv { font-size: 12px; gap: 2px 14px; }
.solution a { color: var(--gold-strong); text-decoration: none; }
.solution a:hover { text-decoration: underline; }
.pv { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--text-soft); word-break: break-word; }
.note { font-size: 12px; color: var(--text-soft); margin: 6px 0 0; }
pre.raw {
  background: #fdf6e9;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 10px 12px;
  font-size: 12px;
  overflow-x: auto;
  margin: 0;
}

/* Interactive viewer (one per top-N solution). */
.viewer {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.viewer-boards {
  position: relative;
  background: #fdf6e9;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px;
}
.viewer-ply { display: none; line-height: 0; }
.viewer-ply.is-current { display: block; }
.viewer-boards svg { display: block; }
.viewer-controls { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.viewer-controls button {
  background: var(--card-alt);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 10px;
  font-size: 13px;
  cursor: pointer;
  border-radius: 3px;
  font-family: inherit;
}
.viewer-controls button:hover { background: var(--gold); }
.viewer-controls button:disabled { opacity: 0.4; cursor: not-allowed; background: var(--card-alt); }
.viewer-ply-counter { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--text-soft); min-width: 70px; text-align: center; }
.viewer-moves {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  align-items: baseline;
  max-width: 320px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
}
.viewer-moves .move-num { color: var(--text-soft); margin-right: 1px; margin-left: 4px; }
.viewer-moves .move-num:first-child { margin-left: 0; }
.viewer-moves .move-btn {
  background: transparent;
  border: 1px solid transparent;
  color: var(--text);
  padding: 1px 5px;
  font-size: 13px;
  cursor: pointer;
  border-radius: 3px;
  font-family: inherit;
}
.viewer-moves .move-btn:hover { background: var(--card-alt); border-color: var(--border); }
.viewer-moves .move-btn.is-current {
  background: var(--gold);
  color: #4a2f10;
  border-color: var(--gold-strong);
  font-weight: 600;
}
.viewer-moves .move-btn.move-btn-pv { color: var(--text-soft); font-style: italic; }
.viewer-moves .move-btn.move-btn-pv.is-current { color: #4a2f10; font-style: italic; }
.viewer-moves .move-sep {
  color: var(--border);
  margin: 0 5px;
  font-weight: 300;
  user-select: none;
}
.viewer-phase {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 3px;
  background: var(--card-alt);
  color: var(--text-soft);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-left: 6px;
}
.viewer-phase[data-phase="continuation"] {
  background: var(--gold);
  color: #4a2f10;
}
.viewer-hint { font-size: 11px; color: var(--text-soft); font-style: italic; }
"""


_VIEWER_JS: str = r"""
(function () {
  function setPly(viewer, ply) {
    var total = parseInt(viewer.dataset.totalPlies, 10);
    var opening = parseInt(viewer.dataset.openingPlies, 10);
    if (ply < 0) ply = 0;
    if (ply > total - 1) ply = total - 1;
    viewer.dataset.currentPly = String(ply);
    var plies = viewer.querySelectorAll('.viewer-ply');
    for (var i = 0; i < plies.length; i++) {
      var pi = parseInt(plies[i].dataset.ply, 10);
      plies[i].classList.toggle('is-current', pi === ply);
    }
    var moves = viewer.querySelectorAll('.move-btn');
    for (var j = 0; j < moves.length; j++) {
      // move-btn at index k corresponds to ply k+1 (ply 0 has no move).
      var mp = parseInt(moves[j].dataset.ply, 10);
      moves[j].classList.toggle('is-current', mp === ply);
    }
    var counter = viewer.querySelector('.viewer-ply-counter');
    if (counter) counter.textContent = ply + ' / ' + (total - 1);
    var phase = viewer.querySelector('.viewer-phase');
    if (phase && !isNaN(opening)) {
      // Plies 0..opening-1 are the opening; once any PV move has been played
      // (ply >= opening), the badge flips to 'continuation'.
      var isCont = ply >= opening;
      phase.dataset.phase = isCont ? 'continuation' : 'opening';
      phase.textContent = isCont ? 'Continuation' : 'Opening';
    }
    var prevBtn = viewer.querySelector('[data-action="prev"]');
    var startBtn = viewer.querySelector('[data-action="start"]');
    var nextBtn = viewer.querySelector('[data-action="next"]');
    var endBtn = viewer.querySelector('[data-action="end"]');
    if (prevBtn) prevBtn.disabled = ply === 0;
    if (startBtn) startBtn.disabled = ply === 0;
    if (nextBtn) nextBtn.disabled = ply === total - 1;
    if (endBtn) endBtn.disabled = ply === total - 1;
  }

  function step(viewer, delta) {
    setPly(viewer, parseInt(viewer.dataset.currentPly, 10) + delta);
  }

  document.addEventListener('click', function (e) {
    var t = e.target.closest('button');
    if (!t) return;
    var viewer = t.closest('.viewer');
    if (!viewer) return;
    var action = t.dataset.action;
    if (action === 'start') setPly(viewer, 0);
    else if (action === 'prev') step(viewer, -1);
    else if (action === 'next') step(viewer, 1);
    else if (action === 'end') setPly(viewer, parseInt(viewer.dataset.totalPlies, 10) - 1);
    else if (t.classList.contains('move-btn')) {
      setPly(viewer, parseInt(t.dataset.ply, 10));
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
    var viewer = null;
    var active = document.activeElement;
    if (active) viewer = active.closest('.viewer');
    if (!viewer) {
      var open = document.querySelectorAll('details[open] .viewer');
      if (open.length) viewer = open[0];
    }
    if (!viewer) return;
    if (e.key === 'ArrowLeft') { step(viewer, -1); e.preventDefault(); }
    else if (e.key === 'ArrowRight') { step(viewer, 1); e.preventDefault(); }
    else if (e.key === 'Home') { setPly(viewer, 0); e.preventDefault(); }
    else if (e.key === 'End') { setPly(viewer, parseInt(viewer.dataset.totalPlies, 10) - 1); e.preventDefault(); }
  });

  // Initialise each viewer to its starting ply (the value rendered in data-current-ply).
  document.querySelectorAll('.viewer').forEach(function (v) {
    setPly(v, parseInt(v.dataset.currentPly, 10));
  });
})();
"""


# ---------- Helpers ----------


def _line_to_pgn(*, line: list[str]) -> str:
    """Convert a SAN move list into standard PGN move-number form."""
    parts: list[str] = []
    for i, mv in enumerate(line):
        if i % 2 == 0:
            parts.append(f"{i // 2 + 1}. {mv}")
        else:
            parts.append(mv)
    return " ".join(parts)


def _eval_class(*, wp_cp: int | None, terminal: str | None, mate_in: int | None, wp: str) -> str:
    """CSS class for an eval cell, reflecting how good the result is for the WP."""
    if terminal is not None:
        if terminal == "white_wins":
            return "eval-terminal-win" if wp == "white" else "eval-terminal-loss"
        if terminal == "black_wins":
            return "eval-terminal-win" if wp == "black" else "eval-terminal-loss"
        return "eval-terminal-draw"
    if mate_in is not None:
        # Engine-detected mate. Sign convention: positive=white mates.
        white_mates: bool = mate_in > 0
        wp_mates: bool = (white_mates and wp == "white") or (not white_mates and wp == "black")
        return "eval-terminal-win" if wp_mates else "eval-terminal-loss"
    if wp_cp is None:
        return "eval-even"
    if wp_cp >= 300:
        return "eval-wp-best"
    if wp_cp >= 75:
        return "eval-wp-good"
    if wp_cp <= -75:
        return "eval-wp-bad"
    return "eval-even"


def _lichess_link(*, line: list[str], wildcard_player: str) -> str:
    """URL for lichess's analysis board, pre-loaded with the line's full PGN.

    Uses lichess's canonical ``/analysis/pgn/<pgn>`` route (per their routes
    file, ``GET /analysis/pgn/*pgn`` captures the PGN as a path-tail). The
    PGN is URL-encoded so SAN annotations like ``#`` (mate), ``+`` (check),
    and spaces survive intact. ``?color=<white|black>`` orients the board so
    the wildcard player is at the bottom, matching our own diagrams.

    Loading via PGN — rather than FEN — preserves the move history, so the
    user can step backwards through the line in lichess's own viewer.
    """
    pgn: str = _line_to_pgn(line=line)
    color: str = "black" if wildcard_player == "black" else "white"
    return f"https://lichess.org/analysis/pgn/{quote(pgn)}?color={color}"


def _wp_first_move_index(*, wildcard_player: str) -> int:
    """0 if WP is white (their plies are 0,2,4...), 1 if WP is black."""
    return 0 if wildcard_player == "white" else 1


# ---------- Aggregate stats ----------


def _bucket_for_result(*, r: dict[str, Any], wp: str) -> str:
    """Place a single result into one of the histogram buckets."""
    terminal: str | None = r["terminal"]
    mate_in: int | None = r["mate_in"]
    wp_cp: int | None = r["wildcard_player_centipawns"]

    if terminal is not None:
        if terminal in ("white_wins", "black_wins"):
            wp_won: bool = (terminal == "white_wins" and wp == "white") or (
                terminal == "black_wins" and wp == "black"
            )
            return "term_wp_wins" if wp_won else "term_wp_loses"
        return "term_draw"

    if mate_in is not None:
        white_mates: bool = mate_in > 0
        wp_mates: bool = (white_mates and wp == "white") or (not white_mates and wp == "black")
        return "engine_mate_for_wp" if wp_mates else "engine_mate_vs_wp"

    if wp_cp is None:
        return "even"
    if wp_cp >= 500:
        return "wp_winning_big"
    if wp_cp >= 100:
        return "wp_winning"
    if wp_cp > -100:
        return "even"
    if wp_cp > -500:
        return "wp_losing"
    return "wp_losing_big"


_BUCKET_ORDER: list[tuple[str, str, str]] = [
    # (key, human label, css modifier)
    ("term_wp_wins", "WP wins by checkmate", "is-good"),
    ("engine_mate_for_wp", "Engine sees mate for WP", "is-good"),
    ("wp_winning_big", "WP ≥ +5.00", "is-good"),
    ("wp_winning", "WP +1.00 to +5.00", "is-good"),
    ("even", "Roughly even (−1.00 to +1.00)", "is-even"),
    ("wp_losing", "WP −5.00 to −1.00", "is-bad"),
    ("wp_losing_big", "WP ≤ −5.00", "is-bad"),
    ("engine_mate_vs_wp", "Engine sees mate against WP", "is-bad"),
    ("term_wp_loses", "WP checkmated", "is-bad"),
    ("term_draw", "Draw (terminal)", "is-even"),
]


def _compute_aggregate_stats(*, results: list[dict[str, Any]], wildcard_player: str) -> dict[str, Any]:
    """Crunch the per-leaf results into summary numbers used by multiple sections."""
    n: int = len(results)
    buckets: dict[str, int] = defaultdict(int)
    cps: list[int] = []
    line_lengths: list[int] = []
    line_length_counts: dict[int, int] = defaultdict(int)

    for r in results:
        buckets[_bucket_for_result(r=r, wp=wildcard_player)] += 1
        if r["wildcard_player_centipawns"] is not None:
            cps.append(r["wildcard_player_centipawns"])
        line_lengths.append(len(r["line"]))
        line_length_counts[len(r["line"])] += 1

    cp_summary: dict[str, float | int | None] = {
        "count_with_cp": len(cps),
        "best": max(cps) if cps else None,
        "worst": min(cps) if cps else None,
        "mean": statistics.fmean(cps) if cps else None,
        "median": statistics.median(cps) if cps else None,
        "stdev": statistics.pstdev(cps) if len(cps) > 1 else 0.0 if cps else None,
    }

    return {
        "total": n,
        "buckets": dict(buckets),
        "cp_summary": cp_summary,
        "line_length_counts": dict(sorted(line_length_counts.items())),
        "top_result": results[0] if results else None,
    }


# ---------- Sections ----------


def _header(*, meta: dict[str, Any], stats: dict[str, Any]) -> str:
    tag: str = meta.get("experiment_tag", "untitled")
    spec: str = meta["spec"]
    wp: str = meta["wildcard_player"]
    total: int = stats["total"]
    elapsed: float = meta.get("elapsed_seconds", 0.0)
    top: dict[str, Any] | None = stats["top_result"]
    top_str: str = ""
    if top is not None:
        line_pgn: str = _line_to_pgn(line=top["line"])
        top_str = f'{escape(line_pgn)}&nbsp;&nbsp;→&nbsp;&nbsp;{escape(top["evaluation_str"])}'

    return f"""
<header class="report-header">
  <div class="byline"><a href="https://github.com/mitchellpkt/chess-antivenom" target="_blank" rel="noopener">Antivenom Analysis (MitchellPKT)</a></div>
  <h1>Antivenom Report: {escape(tag)}</h1>
  <div class="subtitle">Spec: {escape(spec)}&nbsp;&nbsp;·&nbsp;&nbsp;Wildcard player: <strong>{escape(wp)}</strong></div>
  <div class="quickstats">
    <span><strong>{total}</strong>leaves evaluated</span>
    <span><strong>{elapsed:.1f}s</strong>elapsed</span>
    <span><strong>{(total / elapsed) if elapsed > 0 else 0:.1f}</strong>leaves / sec</span>
    <span><strong>Top:</strong>{top_str}</span>
  </div>
</header>
"""


def _config_card(*, meta: dict[str, Any]) -> str:
    stockfish: dict[str, Any] = meta.get("stockfish", {})
    rows: list[tuple[str, str]] = [
        ("Experiment tag", str(meta.get("experiment_tag", ""))),
        ("Input path", str(meta.get("input_path", ""))),
        ("Spec", str(meta.get("spec", ""))),
        ("Wildcard symbol", str(meta.get("wildcard_symbol", ""))),
        ("Wildcard player", str(meta.get("wildcard_player", ""))),
        ("Stockfish path", str(stockfish.get("path", ""))),
        ("Stockfish depth", str(stockfish.get("depth", ""))),
        ("Stockfish threads", str(stockfish.get("threads", ""))),
        ("Stockfish hash (MB)", str(stockfish.get("hash_mb", ""))),
        ("Total leaves", str(meta.get("total_leaves", ""))),
        ("Elapsed seconds", f"{meta.get('elapsed_seconds', 0):.3f}"),
        ("Evaluated at (unix)", str(meta.get("evaluated_at_unix", ""))),
    ]
    body_rows: str = "".join(
        f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in rows
    )
    return f"""
<details>
  <summary>Configuration</summary>
  <div class="body">
    <dl class="kv">{body_rows}</dl>
  </div>
</details>
"""


def _run_stats_card(*, meta: dict[str, Any], stats: dict[str, Any]) -> str:
    cp: dict[str, Any] = stats["cp_summary"]
    elapsed: float = meta.get("elapsed_seconds", 0.0)
    total: int = stats["total"]

    def _fmt_cp(v: Any) -> str:
        if v is None:
            return "n/a"
        return f"{v / 100:+.2f}  ({int(v):+d} cp)"

    def _fmt_num(v: Any, fmt: str = ".2f") -> str:
        if v is None:
            return "n/a"
        return format(v, fmt)

    rows: list[tuple[str, str]] = [
        ("Total leaves", str(total)),
        ("Leaves with cp eval", str(cp["count_with_cp"])),
        ("Best (for WP)", _fmt_cp(cp["best"])),
        ("Worst (for WP)", _fmt_cp(cp["worst"])),
        ("Mean (for WP)", _fmt_cp(cp["mean"]) if cp["mean"] is not None else "n/a"),
        ("Median (for WP)", _fmt_cp(cp["median"]) if cp["median"] is not None else "n/a"),
        ("Std dev (cp)", _fmt_num(cp["stdev"]) if cp["stdev"] is not None else "n/a"),
        ("Elapsed seconds", f"{elapsed:.2f}"),
        ("Leaves / sec", f"{(total / elapsed) if elapsed > 0 else 0:.2f}"),
    ]
    body_rows: str = "".join(
        f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in rows
    )
    return f"""
<details open>
  <summary>Run summary</summary>
  <div class="body">
    <dl class="kv">{body_rows}</dl>
  </div>
</details>
"""


def _outcome_breakdown(*, stats: dict[str, Any]) -> str:
    total: int = max(stats["total"], 1)
    bucket_counts: dict[str, int] = stats["buckets"]
    max_count: int = max(bucket_counts.values()) if bucket_counts else 1

    bar_rows: list[str] = []
    for key, label, modifier in _BUCKET_ORDER:
        count: int = bucket_counts.get(key, 0)
        if count == 0:
            continue
        pct: float = 100.0 * count / total
        bar_width_pct: float = 100.0 * count / max_count
        bar_rows.append(
            f"""<div class="bar-row {modifier}">
  <div class="label">{escape(label)}</div>
  <div class="count">{count} ({pct:.1f}%)</div>
  <div><div class="bar" style="width: {bar_width_pct:.1f}%;"></div></div>
</div>"""
        )

    line_length_counts: dict[int, int] = stats["line_length_counts"]
    ll_max: int = max(line_length_counts.values()) if line_length_counts else 1
    ll_rows: list[str] = []
    for length, count in line_length_counts.items():
        pct = 100.0 * count / total
        bw = 100.0 * count / ll_max
        ll_rows.append(
            f"""<div class="bar-row is-even">
  <div class="label">Line length {length}</div>
  <div class="count">{count} ({pct:.1f}%)</div>
  <div><div class="bar" style="width: {bw:.1f}%;"></div></div>
</div>"""
        )

    return f"""
<details open>
  <summary>Outcome breakdown</summary>
  <div class="body">
    {''.join(bar_rows) if bar_rows else '<p class="note">No results.</p>'}
    <p class="note" style="margin-top:14px;">Line-length distribution (mate truncation collapses some branches to fewer plies than the full spec):</p>
    {''.join(ll_rows)}
  </div>
</details>
"""


def _per_first_move_card(*, results: list[dict[str, Any]], wildcard_player: str) -> str:
    """Group leaves by the wildcard player's first ply; show best / mean / worst per group."""
    if not results:
        return ""
    wp_idx: int = _wp_first_move_index(wildcard_player=wildcard_player)

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        line: list[str] = r["line"]
        if wp_idx >= len(line):
            continue
        groups[line[wp_idx]].append(r)

    rows: list[tuple[str, int, dict[str, Any], dict[str, Any]]] = []
    for move, group in groups.items():
        cps: list[int] = [g["wildcard_player_centipawns"] for g in group if g["wildcard_player_centipawns"] is not None]
        best_r: dict[str, Any] = max(group, key=lambda g: (g.get("sort_category", 0), g.get("sort_secondary", 0)) if "sort_category" in g else (0, 0))
        # Fall back: best by rank (lower rank = better) since the input list is sorted.
        best_r = min(group, key=lambda g: g["rank"])
        worst_r = max(group, key=lambda g: g["rank"])
        summary: dict[str, Any] = {
            "best_eval": best_r["evaluation_str"],
            "best_line": best_r["line"],
            "best_rank": best_r["rank"],
            "worst_eval": worst_r["evaluation_str"],
            "worst_rank": worst_r["rank"],
            "mean_cp": (statistics.fmean(cps) if cps else None),
        }
        rows.append((move, len(group), summary, best_r))

    # Sort by best-rank ascending (i.e., the WP first move whose best leaf sits highest overall).
    rows.sort(key=lambda x: x[2]["best_rank"])

    body_rows: list[str] = []
    for move, n, summary, best_r in rows:
        mean_str: str = (
            f"{summary['mean_cp'] / 100:+.2f}" if summary["mean_cp"] is not None else "n/a"
        )
        body_rows.append(
            f"""<tr>
  <td class="mono"><strong>{escape(move)}</strong></td>
  <td>{n}</td>
  <td class="eval">{escape(summary['best_eval'])}</td>
  <td>#{summary['best_rank']}</td>
  <td class="mono">{escape(_line_to_pgn(line=summary['best_line']))}</td>
  <td class="eval">{escape(mean_str)}</td>
  <td class="eval">{escape(summary['worst_eval'])}</td>
  <td>#{summary['worst_rank']}</td>
</tr>"""
        )

    return f"""
<details>
  <summary>By wildcard-player first move ({len(rows)} distinct first moves)</summary>
  <div class="body">
    <table>
      <thead>
        <tr>
          <th>WP first move</th>
          <th>Leaves</th>
          <th>Best eval</th>
          <th>Best rank</th>
          <th>Best line</th>
          <th>Mean cp (WP)</th>
          <th>Worst eval</th>
          <th>Worst rank</th>
        </tr>
      </thead>
      <tbody>
        {''.join(body_rows)}
      </tbody>
    </table>
  </div>
</details>
"""


def _replay_line_to_svgs(
    *,
    line: list[str],
    continuation: list[str],
    wildcard_player: str,
    size: int,
) -> tuple[list[str], int]:
    """Replay a SAN opening plus engine continuation; return one SVG per ply.

    Returns ``(svgs, n_continuation_played)``. ``svgs[0]`` is the starting
    position, ``svgs[k]`` is the position after the k-th ply. The first
    ``len(line) + 1`` SVGs cover the opening; any remaining ones cover as
    much of the PV as parsed cleanly. ``n_continuation_played`` is the
    number of continuation plies actually replayed — usually
    ``len(continuation)``, less if the PV had to be truncated.

    Each SVG after the first includes an arrow for the move that led there,
    and a check highlight when the side to move is in check.
    """
    flipped: bool = wildcard_player == "black"
    board: chess.Board = chess.Board()
    svgs: list[str] = [
        chess.svg.board(board=board, size=size, flipped=flipped)
    ]
    # The opening must parse — those moves came from the deterministic
    # spec-expansion in this codebase, so a failure here is a real bug.
    for san in line:
        move: chess.Move = board.parse_san(san)
        board.push(move)
        check_sq: int | None = board.king(board.turn) if board.is_check() else None
        svgs.append(
            chess.svg.board(
                board=board, size=size, flipped=flipped,
                lastmove=move, check=check_sq,
            )
        )
    # PV comes from Stockfish and is normally legal, but defensively truncate
    # at any unparseable move so a single flaky engine output doesn't break
    # the whole report. The opening-only viewer still works.
    n_continuation: int = 0
    for san in continuation:
        try:
            move = board.parse_san(san)
        except (chess.IllegalMoveError, chess.AmbiguousMoveError, chess.InvalidMoveError, ValueError) as e:
            logger.warning(f"PV truncated — could not parse SAN {san!r} from {board.fen()}: {e}")
            break
        board.push(move)
        check_sq = board.king(board.turn) if board.is_check() else None
        svgs.append(
            chess.svg.board(
                board=board, size=size, flipped=flipped,
                lastmove=move, check=check_sq,
            )
        )
        n_continuation += 1
    return svgs, n_continuation


def _interactive_viewer_html(
    *,
    viewer_id: str,
    line: list[str],
    continuation: list[str],
    wildcard_player: str,
    size: int = 280,
) -> str:
    """Build the HTML for one interactive board viewer.

    All per-ply SVGs are pre-rendered server-side and emitted as hidden divs;
    the JS controller in ``_VIEWER_JS`` toggles which one is visible. The
    viewer defaults to the leaf position (ply = ``len(line)``) since that's
    the position the eval refers to. From there, the user can step forward
    into the engine's principal variation. A small badge labels each ply as
    ``Opening`` or ``Continuation``.
    """
    svgs, n_cont = _replay_line_to_svgs(
        line=line,
        continuation=continuation,
        wildcard_player=wildcard_player,
        size=size,
    )
    # Trim the displayed continuation to what was actually replayed so we
    # don't surface clickable move buttons that point at non-existent plies.
    effective_continuation: list[str] = list(continuation[:n_cont])
    total_plies: int = len(svgs)
    # Opening covers plies 0..len(line) (inclusive). ``opening_plies`` is the
    # count of opening plies, i.e. the first PV-extended ply has index ==
    # opening_plies. Continuation plies are ``[opening_plies, total_plies)``.
    opening_plies: int = len(line) + 1
    default_ply: int = len(line)  # leaf position

    ply_divs: list[str] = []
    for i, svg in enumerate(svgs):
        cls: str = "viewer-ply is-current" if i == default_ply else "viewer-ply"
        ply_divs.append(f'<div class="{cls}" data-ply="{i}">{svg}</div>')

    # Move list — interleave move numbers with clickable buttons. Opening
    # moves use the default style; continuation (PV) moves get a softer
    # italic style and a separator marks the boundary.
    move_items: list[str] = []
    for i, san in enumerate(line):
        if i % 2 == 0:
            move_items.append(f'<span class="move-num">{i // 2 + 1}.</span>')
        ply_idx: int = i + 1  # ply 0 is the start; the move at index i lands at ply i+1.
        move_items.append(
            f'<button class="move-btn" type="button" data-ply="{ply_idx}">{escape(san)}</button>'
        )
    if effective_continuation:
        move_items.append(
            '<span class="move-sep" title="end of opening — engine continuation begins">│</span>'
        )
    for j, san in enumerate(effective_continuation):
        overall_idx: int = len(line) + j
        if overall_idx % 2 == 0:
            move_items.append(f'<span class="move-num">{overall_idx // 2 + 1}.</span>')
        ply_idx = overall_idx + 1
        move_items.append(
            f'<button class="move-btn move-btn-pv" type="button" data-ply="{ply_idx}">{escape(san)}</button>'
        )
    move_list: str = "".join(move_items) if move_items else '<span class="viewer-hint">no moves</span>'

    phase_initial: str = "continuation" if default_ply >= opening_plies else "opening"
    phase_label: str = "Continuation" if phase_initial == "continuation" else "Opening"

    return f"""
<div class="viewer" id="{viewer_id}" data-total-plies="{total_plies}" data-opening-plies="{opening_plies}" data-current-ply="{default_ply}" tabindex="0">
  <div class="viewer-boards">{''.join(ply_divs)}</div>
  <div class="viewer-controls">
    <button type="button" data-action="start" aria-label="First ply">|◀</button>
    <button type="button" data-action="prev" aria-label="Previous ply">◀</button>
    <span class="viewer-ply-counter">{default_ply} / {total_plies - 1}</span>
    <button type="button" data-action="next" aria-label="Next ply">▶</button>
    <button type="button" data-action="end" aria-label="Last ply">▶|</button>
    <span class="viewer-phase" data-phase="{phase_initial}">{phase_label}</span>
  </div>
  <div class="viewer-moves">{move_list}</div>
  <p class="viewer-hint">click a move or use ← → ↖ ↘ (Home/End) when focused</p>
</div>
"""


def _solution_block(
    *,
    r: dict[str, Any],
    wildcard_player: str,
    is_top: bool,
    include_svg: bool,
    interactive: bool = False,
) -> str:
    """Render one solution.

    When ``interactive`` is True the static SVG is replaced with a full
    per-ply viewer (move list + nav buttons). When ``include_svg`` is True
    but ``interactive`` is False, a single static SVG of the leaf position
    is shown. When both are False, only text / FEN / lichess link.
    """
    rank: int = r["rank"]
    line: list[str] = r["line"]
    fen: str = r["fen"]
    eval_str: str = r["evaluation_str"]
    eval_cls: str = _eval_class(
        wp_cp=r["wildcard_player_centipawns"],
        terminal=r["terminal"],
        mate_in=r["mate_in"],
        wp=wildcard_player,
    )

    pv: list[str] = r.get("principal_variation") or []
    pv_str: str = " ".join(pv) if pv else "(none — terminal position)"
    cp: int | None = r["centipawns"]
    wp_cp: int | None = r["wildcard_player_centipawns"]
    terminal: str | None = r["terminal"]
    mate_in: int | None = r["mate_in"]
    best_move: str = r["best_move"] or "—"

    extra_rows: list[tuple[str, str]] = [
        ("FEN", fen),
        ("Centipawns (white POV)", "n/a" if cp is None else f"{cp:+d}"),
        ("Centipawns (WP POV)", "n/a" if wp_cp is None else f"{wp_cp:+d}"),
        ("Mate in (plies, white+)", "n/a" if mate_in is None else f"{mate_in:+d}"),
        ("Terminal", terminal or "—"),
        ("Best move from leaf", best_move),
        ("Line length", str(len(line))),
    ]
    kv_html: str = "".join(
        f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in extra_rows
    )

    board_html: str = ""
    if interactive:
        viewer_id: str = f"viewer-{rank}"
        board_html = _interactive_viewer_html(
            viewer_id=viewer_id,
            line=line,
            continuation=pv,
            wildcard_player=wildcard_player,
        )
    elif include_svg:
        board: chess.Board = chess.Board(fen)
        flipped: bool = wildcard_player == "black"
        check_sq: int | None = board.king(board.turn) if board.is_check() else None
        board_html = chess.svg.board(
            board=board,
            size=240,
            flipped=flipped,
            check=check_sq,
        )

    lichess: str = _lichess_link(line=line, wildcard_player=wildcard_player)

    classes: str = "solution solution-top" if is_top else "solution"
    head_line_pgn: str = _line_to_pgn(line=line)

    body: str = f"""
<div class="head">
  <div class="rank">#{rank}</div>
  <div class="line">{escape(head_line_pgn)}</div>
  <div class="eval {eval_cls}">{escape(eval_str)}</div>
</div>
<div class="board-row">
  {board_html}
  <div class="meta-block">
    <dl class="kv">{kv_html}</dl>
    <p class="pv"><strong>PV from leaf:</strong> {escape(pv_str)}</p>
    <p class="note"><a href="{escape(lichess)}" target="_blank" rel="noopener">Open in lichess analysis ↗</a></p>
  </div>
</div>
"""
    return f'<div class="{classes}">{body}</div>'


def _top_solutions_card(
    *,
    results: list[dict[str, Any]],
    wildcard_player: str,
    top_n: int,
) -> str:
    if not results:
        return ""
    top_n = min(top_n, len(results))
    blocks: list[str] = [
        _solution_block(
            r=r,
            wildcard_player=wildcard_player,
            is_top=True,
            include_svg=True,
            interactive=True,
        )
        for r in results[:top_n]
    ]
    return f"""
<details open>
  <summary>Top {top_n} solutions (interactive boards — click a move or use ← →)</summary>
  <div class="body">
    {''.join(blocks)}
  </div>
</details>
"""


def _all_solutions_card(
    *,
    results: list[dict[str, Any]],
    wildcard_player: str,
    top_n: int,
) -> str:
    if len(results) <= top_n:
        return ""
    blocks: list[str] = [
        _solution_block(r=r, wildcard_player=wildcard_player, is_top=False, include_svg=False)
        for r in results[top_n:]
    ]
    return f"""
<details>
  <summary>All other solutions ({len(results) - top_n} more, ranked #{top_n + 1}–#{len(results)})</summary>
  <div class="body">
    {''.join(blocks)}
  </div>
</details>
"""


# ---------- Entry point ----------


def json_to_html(*, data: dict[str, Any], top_n_with_boards: int = 5) -> str:
    """Convert an antivenom results dict into a self-contained HTML report.

    Args:
        data: The dict produced by ``AntivenomResult.to_json_dict()``. Must
            contain ``meta`` and ``results`` keys with the documented shape.
        top_n_with_boards: How many top solutions get an inline SVG board.
            The rest are listed without diagrams (for file-size reasons).

    Returns:
        A single self-contained HTML string. No external CSS, no JavaScript,
        no remote assets. Save it to a file and open it in any browser.
    """
    meta: dict[str, Any] = data["meta"]
    results: list[dict[str, Any]] = data["results"]
    wildcard_player: str = meta["wildcard_player"]

    stats: dict[str, Any] = _compute_aggregate_stats(
        results=results, wildcard_player=wildcard_player
    )

    sections: list[str] = [
        _header(meta=meta, stats=stats),
        _config_card(meta=meta),
        _run_stats_card(meta=meta, stats=stats),
        _outcome_breakdown(stats=stats),
        _per_first_move_card(results=results, wildcard_player=wildcard_player),
        _top_solutions_card(results=results, wildcard_player=wildcard_player, top_n=top_n_with_boards),
        _all_solutions_card(results=results, wildcard_player=wildcard_player, top_n=top_n_with_boards),
    ]
    body: str = "\n".join(sections)
    title: str = f"Antivenom Report: {escape(meta.get('experiment_tag', 'untitled'))}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<link rel="icon" type="image/svg+xml" href="{_FAVICON_DATA_URI}">
<style>{_CSS}</style>
</head>
<body>
<main>
{body}
</main>
<script>{_VIEWER_JS}</script>
</body>
</html>
"""
