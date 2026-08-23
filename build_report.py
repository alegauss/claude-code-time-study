"""Render the HTML report from the measured data.

Produces two files from one template:
  report.html           -- standalone document, open it in a browser
  report.fragment.html  -- same page body, for publishing as an Artifact

Everything the reader can adjust (human baseline rates, activity multipliers,
the estimator inputs) is computed in the browser, so the assumptions stay
visible and changeable instead of baked into a static number.

Usage:
    python build_report.py [--data report_data.json] [--out report.html]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HEAD = """<title>Development Time with Claude Code</title>
<style>
:root {
  color-scheme: light;
  --page:        #f9f9f7;
  --surface:     #fcfcfb;
  --ink:         #0b0b0b;
  --ink-2:       #52514e;
  --muted:       #898781;
  --grid:        #e1e0d9;
  --axis:        #c3c2b7;
  --border:      rgba(11,11,11,0.10);
  --s1: #2a78d6;  --s2: #eb6834;  --s3: #1baf7a;
  --s4: #eda100;  --s5: #e87ba4;  --s6: #008300;
  --measured-bg: rgba(42,120,214,0.07);
  --assumed-bg:  rgba(235,104,52,0.07);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --axis: #383835;
    --border: rgba(255,255,255,0.10);
    --s1: #3987e5; --s2: #d95926; --s3: #199e70;
    --s4: #c98500; --s5: #d55181; --s6: #008300;
    --measured-bg: rgba(57,135,229,0.12);
    --assumed-bg:  rgba(217,89,38,0.12);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --axis: #383835;
  --border: rgba(255,255,255,0.10);
  --s1: #3987e5; --s2: #d95926; --s3: #199e70;
  --s4: #c98500; --s5: #d55181; --s6: #008300;
  --measured-bg: rgba(57,135,229,0.12);
  --assumed-bg:  rgba(217,89,38,0.12);
}

* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--ink);
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 1240px; margin: 0 auto; padding: 48px 32px 96px; }

h1, h2, h3 { text-wrap: balance; }
h1 { font-size: 30px; line-height: 1.25; margin: 0 0 8px; letter-spacing: -0.02em; }
h2 { font-size: 21px; margin: 0 0 6px; letter-spacing: -0.01em; }
h3 { font-size: 15px; margin: 0 0 10px; color: var(--ink-2); font-weight: 600; }
/* Prose runs to the container edge so text and box always end together. The
   readable measure is set by .wrap's max-width, not by a per-paragraph cap --
   a ch-based cap here lands near 60% of the container and reads as broken. */
p  { margin: 0 0 14px; color: var(--ink-2); }
a  { color: var(--s1); }

:focus-visible { outline: 2px solid var(--s1); outline-offset: 2px; border-radius: 3px; }
svg [tabindex]:focus-visible { outline-offset: 0; }
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}

.sub { color: var(--muted); font-size: 14px; margin-bottom: 32px; }
section { margin: 56px 0 0; }
section > p:first-of-type { margin-top: 4px; }
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 22px 24px; margin: 18px 0;
}
.card > h3:first-child { margin-top: 0; }

.tag {
  display: inline-block; font-size: 11px; font-weight: 600;
  letter-spacing: 0.04em; text-transform: uppercase;
  padding: 3px 8px; border-radius: 999px; vertical-align: 2px;
  margin-left: 8px; white-space: nowrap;
}
.tag.measured { background: var(--measured-bg); color: var(--s1); }
.tag.assumed  { background: var(--assumed-bg);  color: var(--s2); }
:root[data-theme="dark"] .tag.measured,
:root:not([data-theme="light"]) .tag.measured { color: var(--ink); }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(168px,1fr)); gap: 12px; margin: 20px 0; }
.kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }
.kpi .lbl { font-size: 12.5px; color: var(--muted); margin-bottom: 6px; line-height: 1.35; }
.kpi .val { font-size: 27px; font-weight: 600; letter-spacing: -0.02em; }
.kpi .val .u { font-size: 15px; font-weight: 500; color: var(--ink-2); margin-left: 2px; }
.kpi .note { font-size: 12px; color: var(--muted); margin-top: 4px; }
.hero { font-size: 52px; font-weight: 600; letter-spacing: -0.03em; line-height: 1; }
.hero .u { font-size: 20px; font-weight: 500; color: var(--ink-2); margin-left: 4px; }

.chart { position: relative; width: 100%; overflow-x: auto; }
.chart svg { display: block; width: 100%; height: auto; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 18px; margin: 14px 0 0; padding: 0; list-style: none; }
.legend li { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--ink-2); }
.legend .sw { width: 11px; height: 11px; border-radius: 3px; flex: none; }
.legend .ln { width: 16px; height: 2px; border-radius: 2px; flex: none; }
.tip {
  position: fixed; pointer-events: none; opacity: 0; transition: opacity .1s;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 11px; font-size: 13px; color: var(--ink-2);
  box-shadow: 0 6px 20px rgba(0,0,0,0.13); z-index: 20; min-width: 130px;
}
.tip .t { color: var(--ink); font-weight: 600; margin-bottom: 4px; font-size: 13px; }
.tip .r { display: flex; align-items: center; gap: 7px; white-space: nowrap; }
.tip .r b { color: var(--ink); font-variant-numeric: tabular-nums; }
.tip .k { width: 14px; height: 2px; border-radius: 2px; flex: none; }

details { margin: 14px 0 0; }
summary { cursor: pointer; font-size: 13px; color: var(--s1); font-weight: 500; }
summary::marker { color: var(--muted); }
table { width: 100%; border-collapse: collapse; margin: 12px 0 0; font-size: 13.5px; }
th, td { text-align: right; padding: 7px 10px; border-bottom: 1px solid var(--grid); }
th:first-child, td:first-child { text-align: left; }
thead th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
tbody td { font-variant-numeric: tabular-nums; color: var(--ink-2); }
tbody td:first-child { color: var(--ink); font-variant-numeric: normal; }
tbody tr.total td { font-weight: 600; color: var(--ink); border-top: 1px solid var(--axis); }
.tbl-scroll { overflow-x: auto; }

.ctrls { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px,1fr)); gap: 16px 24px; }
.ctrl label { display: block; font-size: 13px; color: var(--ink-2); margin-bottom: 6px; }
.ctrl label b { color: var(--ink); font-variant-numeric: tabular-nums; }
.ctrl input[type=range] { width: 100%; accent-color: var(--s1); }
.ctrl input[type=number], .ctrl select {
  width: 100%; padding: 7px 9px; font: inherit; font-size: 14px;
  color: var(--ink); background: var(--page);
  border: 1px solid var(--border); border-radius: 7px;
}
.ctrl small { display: block; margin-top: 4px; line-height: 1.4; font-size: 12px; color: var(--muted); }
.reset {
  font: inherit; font-size: 13px; cursor: pointer; margin-top: 14px;
  background: none; border: 1px solid var(--border); border-radius: 7px;
  padding: 6px 12px; color: var(--ink-2);
}
.reset:hover { color: var(--ink); }

.callout {
  border-left: 3px solid var(--s2); background: var(--assumed-bg);
  border-radius: 0 8px 8px 0; padding: 14px 18px; margin: 18px 0;
}
.callout.info { border-left-color: var(--s1); background: var(--measured-bg); }
.callout p:last-child { margin-bottom: 0; }
.callout strong { color: var(--ink); }

ul.notes { color: var(--ink-2); font-size: 14.5px; padding-left: 22px; }
ul.notes li { margin-bottom: 9px; }
code {
  font: 13px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace;
  background: var(--page); border: 1px solid var(--border);
  border-radius: 5px; padding: 1px 5px;
}
hr { border: 0; border-top: 1px solid var(--grid); margin: 40px 0 0; }
@media (max-width: 640px) {
  .wrap { padding: 32px 16px 64px; }
  .card { padding: 18px 16px; }
  h1 { font-size: 25px; }
  .hero { font-size: 42px; }
}
@media print {
  body { background: #fff; }
  .card, .kpi { break-inside: avoid; }
  details { display: none; }
}

/* ---------- sponsor block (generated from alegauss.github.io/sponsor.json) ----------
   Product tiles carry the real logos on a white plate — reproduced as published,
   never recoloured to match this report's palette. */
.sponsor {
  display: flex; align-items: flex-start; gap: 16px;
  margin-top: 30px; padding: 18px 20px;
  border: 1px solid var(--border); border-radius: 10px; background: var(--surface);
}
.sponsor-mark { width: 42px; height: 42px; border-radius: 9px; flex: none; background: #fff; padding: 3px; }
.sponsor-body { min-width: 0; }
.sponsor-label { font-size: 11px; letter-spacing: .09em; text-transform: uppercase; color: var(--muted); display: block; }
.sponsor-name { font-weight: 700; font-size: 15px; display: block; margin-top: 2px; color: var(--ink); text-decoration: none; }
.sponsor-name:hover { color: var(--s1); }
.sponsor-body p { margin-top: 7px; font-size: 13px; line-height: 1.65; color: var(--ink-2); }
.sponsor-body p a { color: var(--s1); text-decoration: underline; text-underline-offset: 3px; }
.sponsor-products { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
.sponsor-product {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 14px 9px 10px; border: 1px solid var(--border); border-radius: 9px;
  background: var(--page); text-decoration: none; color: var(--ink);
}
.sponsor-product:hover { border-color: var(--axis); }
.sponsor-product img { width: 28px; height: 28px; border-radius: 7px; background: #fff; padding: 2px; flex: none; }
.sponsor-product b { display: block; font-size: 13px; font-weight: 700; }
.sponsor-product small { display: block; font-size: 11.5px; line-height: 1.45; color: var(--muted); max-width: 280px; }
@media (max-width: 620px) {
  .sponsor { flex-direction: column; }
  .sponsor-product { width: 100%; }
}
</style>
"""

BODY = r"""
<div class="wrap">

<h1>Where development time goes with Claude Code</h1>
<p class="sub">
  <b id="s-window"></b> of real usage &middot; <b id="s-sessions"></b> sessions across
  <b id="s-projects"></b> projects &middot; generated <span id="s-generated"></span>
</p>

<div class="callout info">
  <p><strong>How to read this report.</strong> Anything tagged
  <span class="tag measured">measured</span> comes from Claude Code session records and git
  history — it is reproducible and auditable. Anything tagged
  <span class="tag assumed">assumption</span> depends on an estimate of how long a developer
  would have taken by hand, which cannot be measured after the fact. Those assumptions are
  adjustable on this page: move the controls and every number recalculates.</p>
</div>

<section id="summary">
  <h2>1. Summary<span class="tag measured">measured</span></h2>
  <p>Time attributed to development work over the measured period:</p>

  <div class="card">
    <div style="font-size:12.5px;color:var(--muted);margin-bottom:6px">
      Total time attributed to development</div>
    <div class="hero"><span id="h-total"></span><span class="u">hours</span></div>
    <p style="margin:10px 0 0;font-size:14px">
      <span id="h-perday"></span> hours per calendar day across <span id="h-days"></span>
      days. See <a href="#methodology">methodology</a> for the full reconciliation between
      this figure and the <span id="h-span"></span> hours of raw session duration.
    </p>
  </div>

  <div class="kpis" id="kpi-row"></div>
</section>

<section id="split">
  <h2>2. How time splits across activities<span class="tag measured">measured</span></h2>
  <p>This is the central question: how much goes into building the feature, and how much into
     everything else. Each hour is attributed to the activity in progress at that moment,
     reconstructed from the chronological record of every session.</p>

  <div class="card">
    <h3>Hours by activity</h3>
    <div class="chart" id="c-groups"></div>
    <details>
      <summary>View as table</summary>
      <div class="tbl-scroll"><table id="t-groups"></table></div>
    </details>
  </div>

  <div class="callout">
    <p><strong>Against the initial hypothesis.</strong> <span id="hyp-text"></span></p>
  </div>

  <div class="card">
    <h3>Full breakdown, all 11 categories</h3>
    <div class="chart" id="c-phases"></div>
    <details>
      <summary>View as table</summary>
      <div class="tbl-scroll"><table id="t-phases"></table></div>
    </details>
  </div>
</section>

<section id="evidence">
  <h2>3. Evidence: where each hour came from<span class="tag measured">measured</span></h2>
  <p>No hour in this report is extrapolated from a sample. Each is a sum of intervals between
     recorded events. The table below decomposes every category into
     <em>number of operations</em> &times; <em>average duration</em>, so any line can be
     checked independently.</p>

  <div class="card">
    <div class="tbl-scroll"><table id="t-evidence"></table></div>
    <p style="margin:14px 0 0;font-size:13.5px">
      Average duration is the most useful sanity check here: test runs averaging
      <span id="ev-testavg"></span> and builds/lint averaging <span id="ev-verifyavg"></span>
      are consistent with what those operations actually cost, which indicates the time
      attribution is not inflated.
    </p>
  </div>
</section>

<section id="interaction">
  <h2>4. Active tool work vs. human interaction time<span class="tag measured">measured</span></h2>
  <p>Time falls into two distinct regimes. During <b>active work</b> Claude Code is executing
     and the developer follows along. During <b>interaction time</b> the tool is idle, waiting
     on a human — this is where reviewing the result and manual testing live.</p>

  <div class="card">
    <div class="chart" id="c-split"></div>
    <ul class="legend" id="l-split"></ul>
    <details>
      <summary>View as table</summary>
      <div class="tbl-scroll"><table id="t-split"></table></div>
    </details>
  </div>

  <div class="kpis" id="kpi-inter"></div>

  <div class="callout">
    <p><strong>On manual testing.</strong> The <span id="mt-hours"></span> hours classified as
    manual testing are a <em>floor</em>, not a total. They count only the pauses where the
    developer's next message showed evidence of hands-on testing — a pasted screenshot, an
    error report, a confirmation that something worked. Manual testing done silently, or after
    a session ended, appears in no record. See
    <a href="#instrumentation">instrumentation</a> for how to measure this directly.</p>
  </div>
</section>

<section id="maturity">
  <h2>5. The effect of project maturity<span class="tag measured">measured</span></h2>
  <p>The hypothesis that mature projects spend proportionally more effort on tests holds, and
     holds strongly. Each dot is a project; dot size is total hours in it. The line is the
     hours-weighted fit.</p>

  <div class="card">
    <h3>Test share of total time, by project maturity</h3>
    <div class="chart" id="c-scatter"></div>
    <ul class="legend" id="l-scatter"></ul>
    <p id="fit-text" style="margin:14px 0 0;font-size:13.5px"></p>
    <details>
      <summary>View as table</summary>
      <div class="tbl-scroll"><table id="t-scatter"></table></div>
    </details>
  </div>

  <div class="callout info">
    <p><strong>How maturity is computed.</strong> A 0–100 index combining three independent
    signals taken from the repository itself: source size (weight 35%), age of git history
    (25%), and the ratio of test lines to source lines (40%). It is deliberately crude — its
    job is to order projects along an axis, not to be an absolute measure.</p>
  </div>

  <div class="card">
    <h3>Month over month</h3>
    <div class="chart" id="c-months"></div>
    <ul class="legend" id="l-months"></ul>
    <details>
      <summary>View as table</summary>
      <div class="tbl-scroll"><table id="t-months"></table></div>
    </details>
    <p style="margin:14px 0 0;font-size:13.5px" id="months-note"></p>
  </div>
</section>

<section id="comparison">
  <h2>6. With and without Claude Code<span class="tag assumed">assumption</span></h2>
  <p>This is where the analysis stops being measurement. How long the same work would have
     taken without the tool does not exist in the data — it can only be modelled. So
     <b>two independent models</b> are presented, with visible and adjustable assumptions.
     They answer different questions and land on very different numbers; the distance between
     them is itself informative.</p>

  <div class="kpis" id="kpi-compare"></div>

  <div class="card">
    <h3>Model A — per-activity multipliers</h3>
    <p style="font-size:14px">For each measured activity, how many times longer a developer
       would take doing the same thing by hand. Assumes <b>the same work and the same
       decisions</b> — the conservative scenario.</p>
    <div class="ctrls" id="ctrl-mult"></div>
    <button class="reset" id="reset-mult">Restore defaults</button>
    <div class="chart" id="c-modelA" style="margin-top:20px"></div>
    <details>
      <summary>View as table</summary>
      <div class="tbl-scroll"><table id="t-modelA"></table></div>
    </details>
  </div>

  <div class="card">
    <h3>Model B — delivered lines written by hand</h3>
    <p style="font-size:14px">Applies a human authoring rate, in lines per hour, to the lines
       that actually landed in the repositories. Assumes <b>the entire delivered scope would
       have been written by hand</b> — the upper bound.</p>
    <div class="ctrls" id="ctrl-rates"></div>
    <button class="reset" id="reset-rates">Restore defaults</button>
    <div class="chart" id="c-modelB" style="margin-top:20px"></div>
    <details>
      <summary>View as table</summary>
      <div class="tbl-scroll"><table id="t-modelB"></table></div>
    </details>
  </div>

  <div class="callout">
    <p><strong>Why the two models diverge so widely.</strong> <span id="diverge-text"></span></p>
  </div>
</section>

<section id="estimator">
  <h2>7. Estimator for a new project<span class="tag assumed">assumption</span></h2>
  <p>The measured coefficients put to practical use: describe a project's size and profile and
     the page projects hours per activity, using the rates and maturity adjustments observed
     across the <span id="est-n"></span> projects in the fitted sample.</p>

  <div class="card">
    <div class="ctrls" id="ctrl-est"></div>
    <button class="reset" id="reset-est">Restore defaults</button>
  </div>

  <div class="kpis" id="kpi-est"></div>

  <div class="card">
    <h3>Predicted effort distribution</h3>
    <div class="chart" id="c-est"></div>
    <details>
      <summary>View as table</summary>
      <div class="tbl-scroll"><table id="t-est"></table></div>
    </details>
    <p style="margin:14px 0 0;font-size:13.5px" id="est-note"></p>
  </div>
</section>

<section id="projects">
  <h2>8. Projects in the sample<span class="tag measured">measured</span></h2>
  <p>Own projects with at least one hour of attributed time.</p>
  <div class="card">
    <div class="tbl-scroll"><table id="t-projects"></table></div>
    <p style="margin:14px 0 0;font-size:13.5px" id="projects-note"></p>
  </div>
</section>

<section id="methodology">
  <h2>9. Methodology, audit and limitations</h2>

  <h3 style="margin-top:22px">9.1 Time reconciliation<span class="tag measured">measured</span></h3>
  <p>Raw session duration is far larger than attributed time, because long gaps are not work.
     Nothing is discarded silently — the arithmetic closes:</p>
  <div class="card">
    <div class="tbl-scroll"><table id="t-audit"></table></div>
  </div>

  <h3 style="margin-top:22px">9.2 How time is attributed</h3>
  <ul class="notes">
    <li>Each session is rebuilt as a chronological event stream: developer instructions, tool
        actions, and their results. The interval between two consecutive events is attributed
        to the activity in progress during that interval.</li>
    <li>An action is classified by what it does: editing a test file is test authoring; running
        <code>pytest</code>, <code>node --test</code> or <code>mvn test</code> is test
        execution; editing <code>.md</code> is documentation, and so on. The complete rules
        live in <code>classify.py</code>.</li>
    <li><b>Per-event caps.</b> A work interval counts for at most <span id="m-cap"></span>
        minutes; test runs and builds, which legitimately block for longer, count up to
        <span id="m-slowcap"></span> minutes. Pauses waiting on a human count up to
        <span id="m-humancap"></span> minutes. Gaps beyond <span id="m-break"></span> minutes
        are treated as a break and discarded entirely.</li>
    <li>The caps are conservative by design: they <em>reduce</em> the measured total. The
        effect is to understate time, never to inflate it.</li>
  </ul>

  <h3 style="margin-top:22px">9.3 How delivered lines are counted</h3>
  <ul class="notes">
    <li>The official count is an <b>end-to-end diff</b>: from the last commit before the first
        session to the current state. This is reproducible in two commands and cannot
        double-count a file that was revised many times.</li>
    <li>Summing per-commit additions gives a larger number — the <em>churn</em>. In this sample
        it is <span id="m-churn"></span>&times; net delivery, meaning rework exists but is
        moderate.</li>
    <li>Lockfiles, build output, minified bundles and generated directories are excluded, as
        are bot commits (dependabot, copilot).</li>
  </ul>

  <h3 style="margin-top:22px">9.4 Limitations — what these numbers do not prove</h3>
  <ul class="notes">
    <li><b>Section 6 is a model, not a measurement.</b> No observed data says how long the same
        work would have taken by hand. The two models bracket a range; neither is a fact.</li>
    <li><b>Lines of code are a weak proxy for value.</b> They measure volume, not difficulty.
        A 40-line algorithm can cost more than 4,000 lines of repetitive scaffolding. Model A
        exists precisely so the comparison does not have to rely on this measure.</li>
    <li><b>Scope is not constant.</b> Some of what was delivered would likely never have been
        written by hand — exhaustive tests and extensive documentation become worth writing
        once producing them gets cheap. This inflates Model B and is the main reason the two
        models diverge.</li>
    <li><b>A reliable before/after comparison was not possible.</b> It was attempted and the
        output is kept in <code>before_after.json</code>, but the data does not support a
        conclusion: <span id="ba-note"></span></li>
    <li><b>Git cannot distinguish assisted from manual commits in this environment</b>, by
        process choice — recorded authorship is always the developer's. So the two populations
        cannot be separated by metadata, and using the co-authorship trailer would produce
        false negatives across most of the history.</li>
    <li><b>Work delegated to subagents is attributed to the parent session.</b> Claude Code
        writes a separate transcript for each subagent and workflow run, under
        <code>&lt;session&gt;/subagents/</code>. Those files are not parsed: while a subagent
        runs, the parent session is already accruing that wall-clock time, so counting both
        would double it. The consequence is that the <em>duration</em> is captured but its
        internal breakdown is credited to exploration rather than to the activities the
        subagent actually performed. Measured directly, that layer holds
        <b>8.5 hours across 113 transcripts — 1.9% of active work</b>, so the distortion is
        small and one-directional.</li>
    <li><b>One developer, one set of projects.</b> Nothing here generalises to other people or
        other codebases without fresh measurement.</li>
    <li><b>Interaction time includes waiting and reading</b>, which would exist without the
        tool as well. That is why it is accounted separately from active work.</li>
  </ul>

  <h3 style="margin-top:22px" id="instrumentation">9.5 Instrumentation for measuring from here on</h3>
  <p>What retrospective analysis cannot see is manual testing and review time spent outside a
     session. That is directly measurable with hooks installed in the projects, which record
     the timestamp of each work cycle. The repository ships the hooks and installation
     instructions; once installed, future editions of this report will have manual test time
     measured rather than estimated as a floor.</p>
</section>

  <!-- sponsor:start — generated from alegauss.github.io/sponsor.json by
       scripts/sync-sponsor.mjs. Edit the JSON, not this block. Kept as static markup
       on purpose: a runtime fetch would keep the sponsor out of the HTML that crawlers
       and LLMs actually read. -->
  <div class="sponsor">
    <img class="sponsor-mark" src="viglet/viglet-logo.png"
         alt="Viglet logo" width="42" height="42" loading="lazy" decoding="async">
    <div class="sponsor-body">
      <span class="sponsor-label">Sponsored by</span>
      <a class="sponsor-name" href="https://www.viglet.org" target="_blank" rel="noopener">Viglet</a>
      <p>
        Open source search and content tools for organisations with a lot to publish — run on your own servers, with no per-user licence. More at
        <a href="https://www.viglet.org" target="_blank" rel="noopener">viglet.org</a>.
      </p>
      <div class="sponsor-products">
        <a class="sponsor-product" href="https://turing.viglet.org" target="_blank" rel="noopener">
          <img src="viglet/turing-logo.png" alt="Viglet Turing ES logo"
               width="28" height="28" loading="lazy" decoding="async">
          <span>
            <b>Viglet Turing ES</b>
            <small>so visitors find what they came for, with AI answers drawn only from your own content</small>
          </span>
        </a>
        <a class="sponsor-product" href="https://shio.viglet.org" target="_blank" rel="noopener">
          <img src="viglet/shio-logo.png" alt="Viglet Shio CMS logo"
               width="28" height="28" loading="lazy" decoding="async">
          <span>
            <b>Viglet Shio CMS</b>
            <small>so a new page goes live the same day, reviewed and approved by your own team</small>
          </span>
        </a>
      </div>
    </div>
  </div>
  <!-- sponsor:end -->

<hr>
<p style="margin-top:24px;font-size:13px;color:var(--muted)">
  Generated by <code>build_report.py</code> from <code>report_data.json</code>. Pipeline:
  <code>analyze.py</code> → <code>repo_metrics.py</code> → <code>git_delta.py</code> →
  <code>before_after.py</code> → <code>model.py</code> → <code>build_report.py</code>.
</p>

<div class="tip" id="tip"></div>
</div>
"""

SCRIPT = r"""
<script>
const D = __DATA__;
const BA = __BA__;

/* ---------------------------------------------------------------- labels */
const PHASE_EN = {
  feature: "Feature code", test_write: "Writing tests",
  test_run: "Running tests", verify: "Build, lint, typecheck",
  run_app: "Running the app", explore: "Reading and searching code",
  docs_write: "Documentation", planning: "Planning",
  config_write: "Configuration", vcs: "Git and commits", other: "Other",
};
const GROUP_EN = {
  feature: "Feature", tests: "Tests", docs: "Docs and planning",
  verify: "Verification", explore: "Code exploration",
  overhead: "Git and infrastructure",
};
const GROUP_ORDER = ["feature", "tests", "docs", "verify", "explore", "overhead"];
const GROUP_COLOR = {
  feature: "var(--s1)", tests: "var(--s2)", docs: "var(--s3)",
  verify: "var(--s4)", explore: "var(--s5)", overhead: "var(--s6)",
};
const KIND_EN = { code: "Source code", test: "Tests", docs: "Documentation", config: "Configuration" };

/* ----------------------------------------------------------------- utils */
const LOC = "en-US";
const nf = (n, d = 0) => (Number.isFinite(n) ? n : 0)
  .toLocaleString(LOC, { minimumFractionDigits: d, maximumFractionDigits: d });
const hh = (n) => nf(n, n < 10 ? 1 : 0);
const pc = (n) => nf(n, 1) + "%";
const xm = (n) => nf(n, n < 10 ? 1 : 0) + "×";
const NS = "http://www.w3.org/2000/svg";
const el = (id) => document.getElementById(id);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// Chart drawing width. Charts stretch to their container via CSS, so this is
// picked close to the real rendered width to keep the scale factor near 1 and
// stop label text being blown up.
const CW = 1100;

function mins(sec) {
  const m = sec / 60;
  return m >= 1 ? nf(m, m < 10 ? 0 : 0) : nf(sec, 0) + "s";
}
function dur(sec) {
  if (sec < 60) return nf(sec, sec < 10 ? 1 : 0) + "s";
  return nf(sec / 60, 1) + " min";
}

function svgEl(w, h) {
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("viewBox", `0 0 ${w} ${h}`);
  s.setAttribute("width", w); s.setAttribute("height", h);
  s.setAttribute("role", "img");
  s.setAttribute("style", "min-width:640px");
  return s;
}
function mk(tag, attrs, parent) {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(n);
  return n;
}
function txt(parent, x, y, s, o = {}) {
  const t = mk("text", {
    x, y, fill: o.fill || "var(--muted)", "font-size": o.size || 12,
    "text-anchor": o.anchor || "start", "font-weight": o.weight || 400,
    "dominant-baseline": o.baseline || "middle",
  }, parent);
  t.textContent = s;
  if (o.tabular) t.setAttribute("style", "font-variant-numeric:tabular-nums");
  return t;
}

/* --------------------------------------------------------------- tooltip */
const tip = el("tip");
function showTip(ev, title, rows) {
  const t = document.createElement("div");
  t.className = "t"; t.textContent = title;
  tip.replaceChildren(t);
  for (const r of rows) {
    const d = document.createElement("div");
    d.className = "r";
    if (r.color) {
      const k = document.createElement("span");
      k.className = "k"; k.style.background = r.color;
      d.appendChild(k);
    }
    const b = document.createElement("b"); b.textContent = r.value;
    d.appendChild(b);
    if (r.label) {
      const s = document.createElement("span"); s.textContent = r.label;
      d.appendChild(s);
    }
    tip.appendChild(d);
  }
  tip.style.opacity = "1";
  moveTip(ev);
}
function moveTip(ev) {
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = (ev.clientX ?? 0) + pad, y = (ev.clientY ?? 0) - h - pad;
  if (x + w > window.innerWidth - 8) x = (ev.clientX ?? 0) - w - pad;
  if (y < 8) y = (ev.clientY ?? 0) + pad;
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
const hideTip = () => { tip.style.opacity = "0"; };

function hoverable(node, title, rows) {
  node.addEventListener("pointerenter", (e) => showTip(e, title, rows));
  node.addEventListener("pointermove", moveTip);
  node.addEventListener("pointerleave", hideTip);
  node.setAttribute("tabindex", "0");
  node.addEventListener("focus", () => {
    const r = node.getBoundingClientRect();
    showTip({ clientX: r.left + r.width / 2, clientY: r.top }, title, rows);
  });
  node.addEventListener("blur", hideTip);
}

/* ------------------------------------------------------ horizontal bars */
function hbars(host, rows, opt = {}) {
  host.replaceChildren();
  const W = CW, labelW = opt.labelW || 205, valW = opt.valW || 150;
  const barH = 20, gap = 16, top = 10;
  const H = top + rows.length * (barH + gap);
  const plotW = W - labelW - valW;
  const max = Math.max(...rows.map((r) => r.value), 0.001);
  const s = svgEl(W, H); host.appendChild(s);

  mk("line", { x1: labelW, y1: top - 5, x2: labelW, y2: H - gap + 5,
               stroke: "var(--axis)", "stroke-width": 1 }, s);

  rows.forEach((r, i) => {
    const y = top + i * (barH + gap);
    txt(s, labelW - 12, y + barH / 2, r.label,
        { anchor: "end", fill: "var(--ink)", size: 13.5 });
    const w = Math.max(2, (r.value / max) * plotW);
    const g = mk("g", {}, s);
    const color = r.color || "var(--s1)";
    mk("rect", { x: labelW + 1, y, width: w, height: barH, rx: 4, fill: color }, g);
    // Square the baseline end: the bar grows out of the axis, not off it.
    mk("rect", { x: labelW + 1, y, width: Math.min(5, w), height: barH, fill: color }, g);
    txt(s, labelW + w + 12, y + barH / 2, opt.fmt ? opt.fmt(r) : hh(r.value) + " h",
        { anchor: "start", fill: "var(--ink)", size: 13, weight: 600, tabular: true });
    if (r.sub) {
      txt(s, labelW + w + 12 + (opt.subOffset || 66), y + barH / 2, r.sub,
          { anchor: "start", size: 12.5, tabular: true });
    }
    const hit = mk("rect", { x: labelW, y: y - gap / 2, width: plotW + valW,
                             height: barH + gap, fill: "transparent" }, g);
    hoverable(hit, r.label, r.tip || [
      { value: (opt.fmt ? opt.fmt(r) : hh(r.value) + " h"), color,
        label: r.sub || "" },
    ]);
  });
  return s;
}

/* --------------------------------------------------- one stacked bar row */
function stackRow(host, segs, opt = {}) {
  host.replaceChildren();
  const W = CW, barH = opt.barH || 34, top = 8, H = top + barH + 10;
  const total = segs.reduce((a, b) => a + b.value, 0) || 1;
  const s = svgEl(W, H); host.appendChild(s);
  let x = 0;
  segs.forEach((sg) => {
    const w = (sg.value / total) * W;
    const g = mk("g", {}, s);
    // 2px surface gap does the separating; no strokes around marks.
    mk("rect", { x, y: top, width: Math.max(1, w - 2), height: barH, rx: 3,
                 fill: sg.color }, g);
    if (w > 108) {
      txt(s, x + 12, top + barH / 2, hh(sg.value) + " h  " + pc(100 * sg.value / total),
          { fill: "#fff", size: 13, weight: 600, tabular: true });
    }
    hoverable(g, sg.label, [
      { value: hh(sg.value) + " h", color: sg.color, label: pc(100 * sg.value / total) },
    ]);
    x += w;
  });
  return s;
}

/* --------------------------------------------------- stacked columns */
function stackedCols(host, cats, series) {
  host.replaceChildren();
  const W = CW, H = 300, padL = 58, padR = 12, padT = 14, padB = 48;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const totals = cats.map((c) => series.reduce((a, sr) => a + (sr.data[c.key] || 0), 0));
  const max = Math.max(...totals, 1);
  const step = Math.pow(10, Math.floor(Math.log10(max / 4)));
  const nice = Math.ceil(max / (step * 4)) * step * 4;
  const s = svgEl(W, H); host.appendChild(s);

  for (let i = 0; i <= 4; i++) {
    const v = (nice / 4) * i, y = padT + plotH - (v / nice) * plotH;
    mk("line", { x1: padL, y1: y, x2: W - padR, y2: y,
                 stroke: i === 0 ? "var(--axis)" : "var(--grid)", "stroke-width": 1 }, s);
    txt(s, padL - 10, y, nf(v) + " h", { anchor: "end", size: 11.5, tabular: true });
  }

  const band = plotW / cats.length;
  const bw = Math.min(56, band * 0.42);
  cats.forEach((c, i) => {
    const cx = padL + band * (i + 0.5);
    let yB = padT + plotH;
    series.forEach((sr) => {
      const v = sr.data[c.key] || 0;
      if (v <= 0) return;
      const hpx = (v / nice) * plotH;
      const g = mk("g", {}, s);
      mk("rect", { x: cx - bw / 2, y: yB - hpx + 2, width: bw,
                   height: Math.max(1, hpx - 2), rx: 3, fill: sr.color }, g);
      hoverable(g, c.label + " · " + sr.label, [{ value: hh(v) + " h", color: sr.color }]);
      yB -= hpx;
    });
    txt(s, cx, padT + plotH + 18, c.label, { anchor: "middle", size: 12.5, fill: "var(--ink)" });
    txt(s, cx, padT + plotH + 34, hh(totals[i]) + " h", { anchor: "middle", size: 11.5, tabular: true });
  });
  return s;
}

/* ------------------------------------------------------------- scatter */
function scatterPlot(host, pts, fit, opt = {}) {
  host.replaceChildren();
  const W = CW, H = 350, padL = 58, padR = 24, padT = 16, padB = 52;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const yMax = Math.max(50, Math.ceil(Math.max(...pts.map((p) => p.y)) / 10) * 10);
  const X = (v) => padL + (v / 100) * plotW;
  const Y = (v) => padT + plotH - (v / yMax) * plotH;
  const s = svgEl(W, H); host.appendChild(s);

  for (let i = 0; i <= 5; i++) {
    const v = (yMax / 5) * i, y = Y(v);
    mk("line", { x1: padL, y1: y, x2: W - padR, y2: y,
                 stroke: i === 0 ? "var(--axis)" : "var(--grid)", "stroke-width": 1 }, s);
    txt(s, padL - 10, y, nf(v) + "%", { anchor: "end", size: 11.5, tabular: true });
  }
  for (let v = 0; v <= 100; v += 20) {
    txt(s, X(v), padT + plotH + 20, nf(v), { anchor: "middle", size: 11.5, tabular: true });
  }
  txt(s, padL + plotW / 2, H - 12, opt.xLabel || "Project maturity index",
      { anchor: "middle", size: 12.5, fill: "var(--ink-2)" });

  if (fit) {
    const xStart = fit.b !== 0 && fit.a < 0 ? clamp(-fit.a / fit.b, 0, 100) : 0;
    mk("line", {
      x1: X(xStart), y1: Y(clamp(fit.a + fit.b * xStart, 0, yMax)),
      x2: X(100), y2: Y(clamp(fit.a + fit.b * 100, 0, yMax)),
      stroke: "var(--s2)", "stroke-width": 2, "stroke-linecap": "round",
    }, s);
  }

  const wMax = Math.max(...pts.map((p) => p.w), 1);
  pts.forEach((p) => {
    const r = 5 + 13 * Math.sqrt(p.w / wMax);
    const g = mk("g", {}, s);
    mk("circle", { cx: X(p.x), cy: Y(p.y), r, fill: "var(--s1)", "fill-opacity": 0.72,
                   stroke: "var(--surface)", "stroke-width": 2 }, g);
    const hit = mk("circle", { cx: X(p.x), cy: Y(p.y), r: Math.max(15, r), fill: "transparent" }, g);
    hoverable(hit, p.label, [
      { value: pc(p.y), label: "of time on tests", color: "var(--s1)" },
      { value: nf(p.x, 1), label: "maturity index" },
      { value: hh(p.w) + " h", label: "time in project" },
    ]);
  });
  return s;
}

/* ----------------------------------------------------------- table + legend */
function table(host, cols, rows, totalRow) {
  host.replaceChildren();
  const thead = document.createElement("thead");
  const tr = document.createElement("tr");
  cols.forEach((c) => { const th = document.createElement("th"); th.textContent = c; tr.appendChild(th); });
  thead.appendChild(tr); host.appendChild(thead);
  const tb = document.createElement("tbody");
  const addRow = (vals, cls) => {
    const t = document.createElement("tr");
    if (cls) t.className = cls;
    vals.forEach((v) => { const td = document.createElement("td"); td.textContent = v; t.appendChild(td); });
    tb.appendChild(t);
  };
  rows.forEach((r) => addRow(r));
  if (totalRow) addRow(totalRow, "total");
  host.appendChild(tb);
}
function legend(host, items, kind = "sw") {
  host.replaceChildren();
  items.forEach((i) => {
    const li = document.createElement("li");
    const sw = document.createElement("span");
    sw.className = kind; sw.style.background = i.color;
    li.appendChild(sw);
    const s = document.createElement("span"); s.textContent = i.label;
    li.appendChild(s);
    host.appendChild(li);
  });
}

/* ================================================================ MODELS */
const T = D.totals;
const ACT = T.active_h, HUM = T.human_h, TOT = ACT + HUM;
const DEL = T.delivered;
const DEL_TOTAL = DEL.code + DEL.test + DEL.docs + DEL.config;

const MULT_DEF = {
  feature: 10, test_write: 12, test_run: 1.2, docs: 5.8,
  verify: 1.35, explore: 3, overhead: 2.25, human: 1,
};
const MULT_MAP = {
  feature: ["feature"], test_write: ["test_write"], test_run: ["test_run"],
  docs: ["docs_write", "planning"], verify: ["verify", "run_app"],
  explore: ["explore"], overhead: ["vcs", "config_write", "other"],
};
const MULT_EN = {
  feature: "Writing feature code", test_write: "Writing tests",
  test_run: "Running tests", docs: "Docs and planning",
  verify: "Build, lint, run", explore: "Reading and navigating code",
  overhead: "Git and infrastructure", human: "Human interaction and review",
};
const MULT_HELP = {
  feature: "A developer hand-writing the same logic.",
  test_write: "Tests are repetitive — where generation gains most.",
  test_run: "Machine time; nearly identical either way.",
  docs: "Writing documentation and plans by hand.",
  verify: "Builds cost the same; add the cost of triggering them manually.",
  explore: "Navigating unfamiliar code without assisted search.",
  overhead: "Commits, branches and config done by hand.",
  human: "Exists in both scenarios; leave at 1.0 unless justified.",
};
const MULT_COLOR = {
  feature: "var(--s1)", test_write: "var(--s2)", test_run: "var(--s2)",
  docs: "var(--s3)", verify: "var(--s4)", explore: "var(--s5)",
  overhead: "var(--s6)", human: "var(--muted)",
};
let mult = { ...MULT_DEF };

function modelA(m) {
  const segs = Object.keys(MULT_MAP).map((k) => {
    const real = MULT_MAP[k].reduce((a, p) => a + (T.phases_h[p] || 0), 0);
    return { key: k, label: MULT_EN[k], real, value: real * m[k], mult: m[k],
             color: MULT_COLOR[k] };
  });
  segs.push({ key: "human", label: MULT_EN.human, real: HUM, value: HUM * m.human,
              mult: m.human, color: MULT_COLOR.human });
  const total = segs.reduce((a, b) => a + b.value, 0);
  return { segs, total, ratio: total / TOT };
}

let rates = { ...D.baseline_defaults };
const RATE_LABEL = {
  rate_code: "Source code", rate_test: "Test code",
  rate_docs: "Documentation", rate_config: "Configuration",
};

function modelB(r) {
  const rows = [
    { key: "code", label: KIND_EN.code, lines: DEL.code, rate: r.rate_code },
    { key: "test", label: KIND_EN.test, lines: DEL.test, rate: r.rate_test },
    { key: "docs", label: KIND_EN.docs, lines: DEL.docs, rate: r.rate_docs },
    { key: "config", label: KIND_EN.config, lines: DEL.config, rate: r.rate_config },
  ].map((x) => ({ ...x, value: x.lines / Math.max(1, x.rate) }));
  const authoring = rows.reduce((a, b) => a + b.value, 0);
  const uplift = 1 + (r.overhead_pct + r.manual_verify_pct) / 100;
  const total = authoring * uplift;
  return { rows, authoring, uplift, total, ratio: total / TOT };
}

/* --------------------------------------------------------- the estimator */
const FITS = D.fits;
const TW = T.phases_h.test_write || 0, TR = T.phases_h.test_run || 0;
const TEST_WRITE_FRAC = TW / Math.max(0.001, TW + TR);
const HUMAN_FRAC = HUM / TOT;
const PROFILES = {
  greenfield: { mat: 15, label: "New project (greenfield)" },
  growing: { mat: 40, label: "Growing" },
  mature: { mat: 70, label: "Mature" },
  legacy: { mat: 90, label: "Large legacy" },
};
const EST_DEF = {
  codeLoc: 20000, profile: "growing", testPct: -1,
  docsPct: Math.round(100 * DEL.docs / Math.max(1, DEL.code)),
  configPct: Math.round(100 * DEL.config / Math.max(1, DEL.code)),
  hoursPerDay: 6,
};
let est = { ...EST_DEF };

const fitTestShare = (mat) => clamp(FITS.test_share_vs_maturity.a
  + FITS.test_share_vs_maturity.b * mat, 0, 60);
const fitFeatShare = (mat) => clamp(FITS.feature_share_vs_maturity.a
  + FITS.feature_share_vs_maturity.b * mat, 3, 32);
const fitThroughput = (mat) => clamp(FITS.throughput_vs_maturity.a
  + FITS.throughput_vs_maturity.b * mat, 250, 2500);
// Test lines as a share of source lines, read off the maturity index, whose
// coverage term is the test-to-source ratio itself.
const defaultTestPct = (mat) => Math.round(clamp(mat * 1.05, 0, 120));

function ratio(part, whole) { return whole > 0 ? part / whole : 0; }

function estimate(e) {
  const mat = PROFILES[e.profile].mat;
  const testPct = e.testPct < 0 ? defaultTestPct(mat) : e.testPct;
  const lines = {
    code: e.codeLoc,
    test: Math.round(e.codeLoc * testPct / 100),
    docs: Math.round(e.codeLoc * e.docsPct / 100),
    config: Math.round(e.codeLoc * e.configPct / 100),
  };
  const total = lines.code + lines.test + lines.docs + lines.config;
  const thr = fitThroughput(mat);
  const engaged = total / thr;
  const active = engaged * (1 - HUMAN_FRAC);
  const human = engaged * HUMAN_FRAC;

  const tShare = fitTestShare(mat), fShare = fitFeatShare(mat);
  const rest = Math.max(0, 100 - tShare - fShare);
  const others = ["docs", "verify", "explore", "overhead"];
  const othersSum = others.reduce((a, g) => a + T.groups_h[g], 0);
  const groups = { feature: active * fShare / 100, tests: active * tShare / 100 };
  others.forEach((g) => { groups[g] = active * (rest / 100) * ratio(T.groups_h[g], othersSum); });

  const dSum = T.phases_h.docs_write + T.phases_h.planning;
  const vSum = T.phases_h.verify + T.phases_h.run_app;
  const oSum = T.phases_h.vcs + T.phases_h.config_write + T.phases_h.other;
  const phases = {
    feature: groups.feature,
    test_write: groups.tests * TEST_WRITE_FRAC,
    test_run: groups.tests * (1 - TEST_WRITE_FRAC),
    docs_write: groups.docs * ratio(T.phases_h.docs_write, dSum),
    planning: groups.docs * ratio(T.phases_h.planning, dSum),
    verify: groups.verify * ratio(T.phases_h.verify, vSum),
    run_app: groups.verify * ratio(T.phases_h.run_app, vSum),
    explore: groups.explore,
    vcs: groups.overhead * ratio(T.phases_h.vcs, oSum),
    config_write: groups.overhead * ratio(T.phases_h.config_write, oSum),
    other: groups.overhead * ratio(T.phases_h.other, oSum),
  };

  let baseA = human * mult.human;
  for (const k in MULT_MAP) {
    baseA += MULT_MAP[k].reduce((a, p) => a + (phases[p] || 0), 0) * mult[k];
  }
  const authoring = lines.code / Math.max(1, rates.rate_code)
    + lines.test / Math.max(1, rates.rate_test)
    + lines.docs / Math.max(1, rates.rate_docs)
    + lines.config / Math.max(1, rates.rate_config);
  const baseB = authoring * (1 + (rates.overhead_pct + rates.manual_verify_pct) / 100);

  return { mat, testPct, lines, total, thr, engaged, active, human, groups, phases,
           baseA, baseB, days: engaged / Math.max(0.5, e.hoursPerDay) };
}

/* ================================================================ RENDER */
function kpis(host, items) {
  host.replaceChildren();
  items.forEach((it) => {
    const d = document.createElement("div"); d.className = "kpi";
    const l = document.createElement("div"); l.className = "lbl"; l.textContent = it.label;
    const v = document.createElement("div"); v.className = "val";
    v.textContent = it.value;
    if (it.unit) {
      const u = document.createElement("span"); u.className = "u"; u.textContent = it.unit;
      v.appendChild(u);
    }
    d.append(l, v);
    if (it.note) {
      const n = document.createElement("div"); n.className = "note"; n.textContent = it.note;
      d.appendChild(n);
    }
    host.appendChild(d);
  });
}

function control(host, cfg) {
  const wrap = document.createElement("div"); wrap.className = "ctrl";
  const lab = document.createElement("label");
  const txtNode = document.createTextNode(cfg.label + " ");
  const b = document.createElement("b");
  lab.append(txtNode, b);
  wrap.appendChild(lab);

  let input;
  if (cfg.type === "select") {
    input = document.createElement("select");
    cfg.options.forEach((o) => {
      const op = document.createElement("option");
      op.value = o.value; op.textContent = o.label;
      input.appendChild(op);
    });
    input.value = cfg.value;
  } else {
    input = document.createElement("input");
    input.type = cfg.type || "range";
    input.min = cfg.min; input.max = cfg.max; input.step = cfg.step ?? 1;
    input.value = cfg.value;
  }
  wrap.appendChild(input);
  if (cfg.help) {
    const s = document.createElement("small"); s.textContent = cfg.help;
    wrap.appendChild(s);
  }
  const sync = () => {
    b.textContent = cfg.fmt ? cfg.fmt(input.value) : input.value;
  };
  sync();
  input.addEventListener("input", () => { sync(); cfg.onInput(input.value); });
  host.appendChild(wrap);
  return { input, sync };
}

/* ---------------------------------------------------------- 1. summary */
function renderSummary() {
  const w = D.window;
  const d0 = new Date(w.first_session * 1000), d1 = new Date(w.last_session * 1000);
  const opts = { month: "short", day: "numeric" };
  const days = (w.last_session - w.first_session) / 86400;
  el("s-window").textContent =
    d0.toLocaleDateString(LOC, opts) + " – " + d1.toLocaleDateString(LOC, { ...opts, year: "numeric" });
  el("s-sessions").textContent = nf(T.counts.sessions);
  el("s-projects").textContent = nf(D.projects.filter((p) => p.active_h >= 1).length);
  el("s-generated").textContent = new Date(D.generated_at).toLocaleDateString(LOC,
    { year: "numeric", month: "long", day: "numeric" });

  el("h-total").textContent = hh(TOT) + " ";
  el("h-perday").textContent = nf(TOT / days, 1);
  el("h-days").textContent = nf(days, 0);
  el("h-span").textContent = nf(T.audit_h.span, 0);

  kpis(el("kpi-row"), [
    { label: "Active tool work", value: hh(ACT), unit: "h",
      note: pc(100 * ACT / TOT) + " of attributed time" },
    { label: "Human interaction time", value: hh(HUM), unit: "h",
      note: pc(100 * HUM / TOT) + " of attributed time" },
    { label: "Lines delivered into git", value: nf(DEL_TOTAL),
      note: nf(DEL.code) + " source, " + nf(DEL.test) + " test" },
    { label: "Commits", value: nf(T.commits),
      note: nf(T.files_delivered) + " files changed" },
    { label: "Test executions", value: nf(T.counts.test_runs),
      note: "avg " + dur(T.phases_h.test_run * 3600 / Math.max(1, T.counts.test_runs)) },
    { label: "Developer instructions", value: nf(T.counts.prompts),
      note: nf(T.counts.tool_uses) + " tool operations" },
  ]);
}

/* ------------------------------------------------------- 2. distribution */
function renderSplit() {
  // One series, one colour: the row label already carries identity, so a
  // second hue per bar would encode nothing. The categorical palette is kept
  // for the stacked charts, where colour does real work.
  const rows = GROUP_ORDER.map((g) => ({
    label: GROUP_EN[g], value: T.groups_h[g],
    sub: pc(100 * T.groups_h[g] / ACT),
  })).sort((a, b) => b.value - a.value);
  hbars(el("c-groups"), rows);
  table(el("t-groups"), ["Activity", "Hours", "Share of active work"],
    rows.map((r) => [r.label, hh(r.value), r.sub]),
    ["Total", hh(ACT), "100.0%"]);

  const feat = 100 * T.groups_h.feature / ACT;
  const tests = 100 * T.groups_h.tests / ACT;
  const docs = 100 * T.groups_h.docs / ACT;
  el("hyp-text").textContent =
    "The expectation was that building the feature would take about 25% of the time, with "
    + "tests and testing taking the rest. Measured, feature code takes " + pc(feat)
    + " — less than half the expected share — while tests take " + pc(tests)
    + " (" + pc(100 * T.phases_h.test_write / ACT) + " writing them, "
    + pc(100 * T.phases_h.test_run / ACT) + " running them) and documentation and planning "
    + "take " + pc(docs) + ". The direction of the hypothesis was right: the feature itself is "
    + "the minority of the work. The magnitude was understated — writing the feature is even "
    + "smaller a slice than expected, and the effort is spread across more activities than "
    + "just testing.";

  const prows = Object.keys(PHASE_EN)
    .map((p) => ({ label: PHASE_EN[p], value: T.phases_h[p],
                   sub: pc(100 * T.phases_h[p] / ACT) }))
    .filter((r) => r.value > 0)
    .sort((a, b) => b.value - a.value);
  hbars(el("c-phases"), prows);
  table(el("t-phases"), ["Category", "Hours", "Share", "Operations"],
    prows.map((r) => {
      const key = Object.keys(PHASE_EN).find((k) => PHASE_EN[k] === r.label);
      return [r.label, hh(r.value), r.sub, nf(T.phase_calls[key] || 0)];
    }),
    ["Total", hh(ACT), "100.0%", nf(Object.values(T.phase_calls).reduce((a, b) => a + b, 0))]);
}

/* ---------------------------------------------------------- 3. evidence */
function renderEvidence() {
  const rows = Object.keys(PHASE_EN)
    .map((k) => ({ k, h: T.phases_h[k] || 0, c: T.phase_calls[k] || 0 }))
    .filter((r) => r.c > 0)
    .sort((a, b) => b.h - a.h);
  table(el("t-evidence"),
    ["Activity", "Operations", "Average duration", "Total hours", "Share"],
    rows.map((r) => [PHASE_EN[r.k], nf(r.c), dur(r.h * 3600 / r.c), hh(r.h),
                     pc(100 * r.h / ACT)]),
    ["Total", nf(rows.reduce((a, b) => a + b.c, 0)), "—", hh(ACT), "100.0%"]);
  el("ev-testavg").textContent =
    dur(T.phases_h.test_run * 3600 / Math.max(1, T.phase_calls.test_run));
  el("ev-verifyavg").textContent =
    dur(T.phases_h.verify * 3600 / Math.max(1, T.phase_calls.verify));
}

/* ------------------------------------------------------- 4. interaction */
function renderInteraction() {
  const segs = [
    { label: "Active tool work", value: ACT, color: "var(--s1)" },
    { label: "Human interaction time", value: HUM, color: "var(--s2)" },
  ];
  stackRow(el("c-split"), segs);
  legend(el("l-split"), segs);
  const hb = T.human_breakdown_h;
  table(el("t-split"), ["Regime", "Hours", "Share"],
    [["Active tool work", hh(ACT), pc(100 * ACT / TOT)],
     ["Interaction — giving direction", hh(hb.direction), pc(100 * hb.direction / TOT)],
     ["Interaction — manual testing", hh(hb.manual_test), pc(100 * hb.manual_test / TOT)],
     ["Interaction — reviewing", hh(hb.review), pc(100 * hb.review / TOT)]],
    ["Total", hh(TOT), "100.0%"]);

  kpis(el("kpi-inter"), [
    { label: "Interaction per developer instruction", value: nf(HUM * 60 / Math.max(1, T.counts.prompts), 1), unit: "min",
      note: nf(T.counts.prompts) + " instructions" },
    { label: "Active work per instruction", value: nf(ACT * 60 / Math.max(1, T.counts.prompts), 1), unit: "min",
      note: "tool executing" },
    { label: "Ratio active : interaction", value: nf(ACT / Math.max(0.01, HUM), 1) + " : 1",
      note: "hours of work per hour of interaction" },
    { label: "Manual testing identified", value: hh(hb.manual_test), unit: "h",
      note: "floor — see note below" },
  ]);
  el("mt-hours").textContent = hh(hb.manual_test);
}

/* --------------------------------------------------------- 5. maturity */
function renderMaturity() {
  const pts = D.projects
    .filter((p) => p.active_h >= D.fits.min_hours_for_fit && p.repo.maturity !== null)
    .map((p) => ({ x: p.repo.maturity, y: 100 * p.groups_h.tests / p.active_h,
                   w: p.active_h, label: p.label }));
  const fit = FITS.test_share_vs_maturity;
  scatterPlot(el("c-scatter"), pts, fit);
  legend(el("l-scatter"), [
    { label: "Project (size = hours spent)", color: "var(--s1)" },
    { label: "Hours-weighted fit", color: "var(--s2)" },
  ]);
  el("fit-text").textContent =
    "Fit: test share = " + nf(fit.a, 1) + " + " + nf(fit.b, 3)
    + " × maturity, R² = " + nf(fit.r2, 2) + " across " + fit.n + " projects. Reading it: "
    + "each 10 points of maturity add roughly " + nf(fit.b * 10, 1)
    + " percentage points of time spent on tests. A greenfield project at maturity 20 sits "
    + "near " + pc(Math.max(0, fit.a + fit.b * 20)) + "; a mature one at 75 sits near "
    + pc(fit.a + fit.b * 75) + ". An R² of " + nf(fit.r2, 2)
    + " means maturity explains most of the variation between projects — this is a strong "
    + "relationship, not a hint.";
  table(el("t-scatter"),
    ["Project", "Maturity", "Test/source ratio", "Test share of time", "Hours"],
    pts.sort((a, b) => a.x - b.x).map((p) => {
      const pr = D.projects.find((q) => q.label === p.label);
      return [p.label, nf(p.x, 1),
              pr.repo.test_ratio !== null ? nf(pr.repo.test_ratio, 2) : "—",
              pc(p.y), hh(p.w)];
    }));

  // A partial first month with under an hour in it is noise on a column chart;
  // the note below the chart says so explicitly.
  const cats = D.months.filter((m) => m.active_h >= 1)
    .map((m) => ({ key: m.month, label: new Date(m.month + "-02T00:00:00Z")
      .toLocaleDateString(LOC, { month: "short", year: "numeric", timeZone: "UTC" }) }));
  const series = GROUP_ORDER.map((g) => ({
    label: GROUP_EN[g], color: GROUP_COLOR[g],
    data: Object.fromEntries(D.months.map((m) => [m.month, m.groups_h[g]])),
  }));
  stackedCols(el("c-months"), cats, series);
  legend(el("l-months"), series);
  table(el("t-months"),
    ["Month", "Active hours", "Interaction", "Test share", "Feature share", "Sessions"],
    D.months.filter((m) => m.active_h > 0.05).map((m) => [
      m.month, hh(m.active_h), hh(m.human_h),
      pc(100 * m.groups_h.tests / m.active_h),
      pc(100 * m.groups_h.feature / m.active_h), nf(m.sessions)]));

  const ms = D.months.filter((m) => m.active_h > 1);
  if (ms.length >= 2) {
    const a = ms[0], b = ms[ms.length - 1];
    el("months-note").textContent =
      "Test share moved from " + pc(100 * a.groups_h.tests / a.active_h) + " in "
      + a.month + " to " + pc(100 * b.groups_h.tests / b.active_h) + " in " + b.month
      + ", while feature share fell from " + pc(100 * a.groups_h.feature / a.active_h)
      + " to " + pc(100 * b.groups_h.feature / b.active_h)
      + ". This is the same maturity effect seen above, playing out over time as the projects "
      + "themselves matured. Note the first partial month is omitted from the chart when it "
      + "holds under an hour of activity.";
  }
}

/* ------------------------------------------------------- 6. comparison */
function renderCompare() {
  const A = modelA(mult), B = modelB(rates);

  kpis(el("kpi-compare"), [
    { label: "Measured, with Claude Code", value: hh(TOT), unit: "h",
      note: "attributed time" },
    { label: "Model A — same work by hand", value: hh(A.total), unit: "h",
      note: xm(A.ratio) + " the measured time" },
    { label: "Model B — same lines by hand", value: nf(B.total, 0), unit: "h",
      note: xm(B.ratio) + " the measured time" },
    { label: "Model A time saved", value: nf(A.total - TOT, 0), unit: "h",
      note: nf((A.total - TOT) / 8, 0) + " working days of 8 h" },
  ]);

  const rowsA = A.segs.slice().sort((a, b) => b.value - a.value).map((s) => ({
    label: s.label, value: s.value,
    sub: xm(s.mult) + " of " + hh(s.real) + " h measured",
    tip: [{ value: hh(s.value) + " h", color: "var(--s1)", label: "modelled by hand" },
          { value: hh(s.real) + " h", label: "measured with the tool" },
          { value: xm(s.mult), label: "multiplier applied" }],
  }));
  hbars(el("c-modelA"), rowsA, { valW: 240, subOffset: 68 });
  table(el("t-modelA"),
    ["Activity", "Measured hours", "Multiplier", "Modelled by hand", "Difference"],
    A.segs.map((s) => [s.label, hh(s.real), xm(s.mult), hh(s.value), hh(s.value - s.real)]),
    ["Total", hh(TOT), xm(A.ratio), hh(A.total), hh(A.total - TOT)]);

  const rowsB = B.rows.slice().sort((a, b) => b.value - a.value).map((r) => ({
    label: r.label, value: r.value, color: "var(--s1)",
    sub: nf(r.lines) + " lines @ " + nf(r.rate) + "/h",
    tip: [{ value: nf(r.value, 0) + " h", color: "var(--s1)", label: "authoring time" },
          { value: nf(r.lines), label: "lines delivered" },
          { value: nf(r.rate) + " lines/h", label: "assumed human rate" }],
  }));
  hbars(el("c-modelB"), rowsB, { valW: 230, subOffset: 68,
    fmt: (r) => nf(r.value, 0) + " h" });
  table(el("t-modelB"),
    ["Kind", "Lines delivered", "Assumed rate", "Authoring hours"],
    B.rows.map((r) => [r.label, nf(r.lines), nf(r.rate) + " lines/h", nf(r.value, 0)]),
    ["Authoring subtotal", nf(DEL_TOTAL), "—", nf(B.authoring, 0)]);

  el("diverge-text").textContent =
    "Model A lands at " + xm(A.ratio) + " and Model B at " + xm(B.ratio)
    + ". The gap is not a contradiction — it is the cost of one assumption. Model B requires "
    + "that all " + nf(DEL_TOTAL) + " delivered lines would have been hand-written. Much of "
    + "that volume exists precisely because producing it became cheap: " + nf(DEL.test)
    + " lines of tests and " + nf(DEL.docs) + " lines of documentation are the kind of work "
    + "that gets trimmed first when a human is writing every line. Model A avoids the question "
    + "of volume entirely and prices the activities actually observed, which is why it is the "
    + "defensible figure for planning. Model B is best read as the ceiling: what the delivered "
    + "artefact would have cost if every line of it had been mandatory.";
}

/* -------------------------------------------------------- 7. estimator */
function renderEstimator() {
  const r = estimate(est);
  el("est-n").textContent = nf(FITS.test_share_vs_maturity.n);

  kpis(el("kpi-est"), [
    { label: "Total lines predicted", value: nf(r.total),
      note: nf(r.lines.code) + " source + " + nf(r.lines.test) + " test" },
    { label: "With Claude Code", value: hh(r.engaged), unit: "h",
      note: hh(r.active) + " h active + " + hh(r.human) + " h interaction" },
    { label: "Calendar estimate", value: nf(r.days, 0), unit: "days",
      note: "at " + nf(est.hoursPerDay) + " h/day" },
    { label: "Without — Model A", value: hh(r.baseA), unit: "h",
      note: xm(r.baseA / r.engaged) + " longer" },
    { label: "Without — Model B", value: nf(r.baseB, 0), unit: "h",
      note: xm(r.baseB / r.engaged) + " longer" },
  ]);

  const rows = GROUP_ORDER.map((g) => ({
    label: GROUP_EN[g], value: r.groups[g],
    sub: pc(100 * r.groups[g] / r.active),
  })).sort((a, b) => b.value - a.value);
  hbars(el("c-est"), rows);
  table(el("t-est"), ["Activity", "Predicted hours", "Share of active work"],
    rows.map((x) => [x.label, hh(x.value), x.sub]),
    ["Active work", hh(r.active), "100.0%"]);

  el("est-note").textContent =
    "Basis: at maturity " + nf(r.mat) + " the sample delivers about " + nf(r.thr, 0)
    + " lines per engaged hour, tests take " + pc(fitTestShare(r.mat))
    + " of active work and feature code " + pc(fitFeatShare(r.mat))
    + ". The throughput relationship is the weakest of the three fits (R² = "
    + nf(FITS.throughput_vs_maturity.r2, 2) + ", n = " + FITS.throughput_vs_maturity.n
    + "), so treat the hour totals as an order of magnitude and the activity split — which "
    + "rests on a much stronger fit — as the more reliable output.";
}

/* --------------------------------------------------------- 8. projects */
// Only own codebases are listed by project. Client repositories are measured
// and included in every total, but not named here.
const LISTED_OWNERS = ["alegauss", "viglet"];

function renderProjects() {
  const all = D.projects.filter((p) => p.active_h >= 1);
  const ps = all.filter((p) => LISTED_OWNERS.includes(p.owner));
  const sum = (f) => ps.reduce((a, p) => a + f(p), 0);
  const sAct = sum((p) => p.active_h), sHum = sum((p) => p.human_h);

  table(el("t-projects"),
    ["Project", "Active h", "Interaction h", "Maturity", "Feature", "Tests", "Docs",
     "Lines delivered", "Commits"],
    ps.map((p) => [
      p.label, hh(p.active_h), hh(p.human_h),
      p.repo.maturity !== null ? nf(p.repo.maturity, 1) : "—",
      pc(100 * p.groups_h.feature / p.active_h),
      pc(100 * p.groups_h.tests / p.active_h),
      pc(100 * p.groups_h.docs / p.active_h),
      nf(Object.values(p.delivered).reduce((a, b) => a + b, 0)),
      nf(p.commits)]),
    ["Subtotal, listed projects", hh(sAct), hh(sHum), "—",
     pc(100 * sum((p) => p.groups_h.feature) / sAct),
     pc(100 * sum((p) => p.groups_h.tests) / sAct),
     pc(100 * sum((p) => p.groups_h.docs) / sAct),
     nf(sum((p) => Object.values(p.delivered).reduce((a, b) => a + b, 0))),
     nf(sum((p) => p.commits))]);

  el("projects-note").textContent =
    "Listed above are the " + ps.length + " openviglet and alegauss projects, which account "
    + "for " + pc(100 * sAct / ACT) + " of all attributed active work. The remaining "
    + (all.length - ps.length) + " projects are client codebases: they are measured and "
    + "included in every total elsewhere in this report, but are not named individually here.";
}

/* ------------------------------------------------------ 9. methodology */
function renderMethodology() {
  const a = T.audit_h;
  table(el("t-audit"), ["Bucket", "Hours", "Share of raw span"],
    [["Raw session span, first to last event", nf(a.span, 0), "100.0%"],
     ["Attributed — active tool work", hh(ACT), pc(100 * ACT / a.span)],
     ["Attributed — human interaction", hh(HUM), pc(100 * HUM / a.span)],
     ["Discarded — above per-event caps", hh(a.capped_out), pc(100 * a.capped_out / a.span)],
     ["Discarded — gaps counted as breaks", nf(a.breaks, 0), pc(100 * a.breaks / a.span)]],
    ["Attributed + discarded", nf(ACT + HUM + a.capped_out + a.breaks, 0), "100.0%"]);

  const at = D.attribution;
  el("m-cap").textContent = nf(at.active_cap_s / 60, 0);
  el("m-slowcap").textContent = nf(at.slow_cap_s / 60, 0);
  el("m-humancap").textContent = nf(at.human_cap_s / 60, 0);
  el("m-break").textContent = nf(at.session_break_s / 60, 0);
  el("m-churn").textContent = nf(T.churn, 2);

  const rs = (BA.repos || []).filter((x) => x.before.net_total > 0 && x.after.net_total > 0);
  const ratios = rs.map((x) => (x.after.net_total / Math.max(1, x.after.active_days))
    / Math.max(0.01, x.before.net_total / Math.max(1, x.before.active_days)));
  const lo = ratios.length ? Math.min(...ratios) : 0;
  const hi = ratios.length ? Math.max(...ratios) : 0;
  el("ba-note").textContent =
    "across " + (BA.repos || []).length + " repositories with comparable windows, the "
    + "per-active-day ratio between the two periods ranges from " + xm(lo) + " to " + xm(hi)
    + " with no interpretable pattern. Two causes dominate. First, the tool was already in use "
    + "before the window being compared — several of these repositories are git worktrees of "
    + "the same codebase, so an earlier version's sessions land inside the supposed "
    + "\"before\" period. Second, in some repositories a single bulk import dominates the "
    + "diff, which swamps any productivity signal. A clean before/after would need a "
    + "repository whose history begins after adoption, and none of these qualify.";
}

/* ------------------------------------------------------------ controls */
function buildMultControls() {
  const host = el("ctrl-mult"); host.replaceChildren();
  Object.keys(MULT_DEF).forEach((k) => {
    control(host, {
      label: MULT_EN[k], min: 1, max: k === "feature" || k === "test_write" ? 25 : 8,
      step: 0.05, value: mult[k], help: MULT_HELP[k],
      fmt: (v) => xm(parseFloat(v)),
      onInput: (v) => { mult[k] = parseFloat(v); renderCompare(); renderEstimator(); },
    });
  });
}
function buildRateControls() {
  const host = el("ctrl-rates"); host.replaceChildren();
  ["rate_code", "rate_test", "rate_docs", "rate_config"].forEach((k) => {
    control(host, {
      label: RATE_LABEL[k], min: 5, max: 120, step: 1, value: rates[k],
      help: "Delivered lines per hour, including debugging and rework.",
      fmt: (v) => nf(parseFloat(v)) + " lines/h",
      onInput: (v) => { rates[k] = parseFloat(v); renderCompare(); renderEstimator(); },
    });
  });
  control(host, {
    label: "Review and integration overhead", min: 0, max: 60, step: 1,
    value: rates.overhead_pct, fmt: (v) => nf(parseFloat(v)) + "%",
    help: "Added on top of authoring time.",
    onInput: (v) => { rates.overhead_pct = parseFloat(v); renderCompare(); renderEstimator(); },
  });
  control(host, {
    label: "Manual verification overhead", min: 0, max: 60, step: 1,
    value: rates.manual_verify_pct, fmt: (v) => nf(parseFloat(v)) + "%",
    help: "Checking by hand what automated runs would have caught.",
    onInput: (v) => { rates.manual_verify_pct = parseFloat(v); renderCompare(); renderEstimator(); },
  });
}
function buildEstControls() {
  const host = el("ctrl-est"); host.replaceChildren();
  control(host, {
    label: "Expected source lines", type: "number", min: 500, max: 2000000, step: 500,
    value: est.codeLoc, fmt: (v) => nf(parseFloat(v)),
    help: "Hand-written source only; tests and docs are derived below.",
    onInput: (v) => { est.codeLoc = Math.max(100, parseFloat(v) || 0); renderEstimator(); },
  });
  control(host, {
    label: "Project profile", type: "select", value: est.profile,
    options: Object.keys(PROFILES).map((k) => ({ value: k, label: PROFILES[k].label })),
    fmt: (v) => "maturity " + PROFILES[v].mat,
    help: "Sets the maturity index driving the fits.",
    onInput: (v) => {
      est.profile = v; est.testPct = -1;
      buildEstControls(); renderEstimator();
    },
  });
  control(host, {
    label: "Test lines, as % of source", min: 0, max: 150, step: 5,
    value: est.testPct < 0 ? defaultTestPct(PROFILES[est.profile].mat) : est.testPct,
    fmt: (v) => nf(parseFloat(v)) + "%",
    help: "Defaults to the profile's own test-to-source ratio.",
    onInput: (v) => { est.testPct = parseFloat(v); renderEstimator(); },
  });
  control(host, {
    label: "Documentation, as % of source", min: 0, max: 80, step: 1,
    value: est.docsPct, fmt: (v) => nf(parseFloat(v)) + "%",
    help: "Sample average is " + EST_DEF.docsPct + "%.",
    onInput: (v) => { est.docsPct = parseFloat(v); renderEstimator(); },
  });
  control(host, {
    label: "Configuration, as % of source", min: 0, max: 80, step: 1,
    value: est.configPct, fmt: (v) => nf(parseFloat(v)) + "%",
    help: "Sample average is " + EST_DEF.configPct + "%.",
    onInput: (v) => { est.configPct = parseFloat(v); renderEstimator(); },
  });
  control(host, {
    label: "Focused hours per day", min: 1, max: 12, step: 0.5,
    value: est.hoursPerDay, fmt: (v) => nf(parseFloat(v), 1) + " h",
    help: "Used only for the calendar estimate.",
    onInput: (v) => { est.hoursPerDay = parseFloat(v); renderEstimator(); },
  });
}

el("reset-mult").addEventListener("click", () => {
  mult = { ...MULT_DEF }; buildMultControls(); renderCompare(); renderEstimator();
});
el("reset-rates").addEventListener("click", () => {
  rates = { ...D.baseline_defaults }; buildRateControls(); renderCompare(); renderEstimator();
});
el("reset-est").addEventListener("click", () => {
  est = { ...EST_DEF }; buildEstControls(); renderEstimator();
});

/* ---------------------------------------------------------------- boot */
renderSummary();
renderSplit();
renderEvidence();
renderInteraction();
renderMaturity();
buildMultControls();
buildRateControls();
buildEstControls();
renderCompare();
renderEstimator();
renderProjects();
renderMethodology();
window.addEventListener("resize", () => { hideTip(); });
</script>
"""


# --------------------------------------------------------------------------
# Head material that only matters for a published page.
# --------------------------------------------------------------------------

META = """<meta name="description" content="A measured breakdown of where development
time actually goes when working with Claude Code: 556 sessions across three months, with
an auditable evidence trail and two adjustable counterfactual models.">
<meta property="og:type" content="article">
<meta property="og:title" content="Where development time goes with Claude Code">
<meta property="og:description" content="Feature code is 11% of the time. Tests are 27%.
Measured from session transcripts and git history, with the methodology shown.">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%E2%8F%B1%EF%B8%8F%3C/text%3E%3C/svg%3E">
"""

# Organisations whose project names may be published. Everything else is a
# client codebase: its numbers stay in every total, its identity does not ship.
PUBLIC_OWNERS = {"alegauss", "viglet"}


def sanitize(data: dict, ba: dict) -> tuple[dict, dict, int]:
    """Strip identifying detail so the page can be published publicly.

    Removes every absolute path, and replaces client project names with
    sequential placeholders. Numeric measurements are untouched, so all totals,
    shares and fits stay exactly as measured -- only identities are withheld.
    """
    redacted = 0
    for p in data.get("projects", []):
        p.pop("cwd", None)
        p.pop("base_commit", None)
        if p.get("owner") not in PUBLIC_OWNERS:
            redacted += 1
            p["label"] = f"Client project {redacted}"
            p["name"] = f"client-{redacted}"
            p["owner"] = "client"

    # The before/after exhibit only ever renders counts and a ratio range, so
    # the safe form is the numbers with no names attached at all.
    ba_clean = {
        "repos": [
            {"before": r["before"], "after": r["after"]}
            for r in ba.get("repos", [])
        ],
        "totals": ba.get("totals", {}),
    }
    for r in ba_clean["repos"]:
        for side in ("before", "after"):
            r[side].pop("from", None)
            r[side].pop("to", None)
    return data, ba_clean, redacted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="report_data.json")
    ap.add_argument("--before-after", default="before_after.json")
    ap.add_argument("--out", default="report.html")
    ap.add_argument("--public", action="store_true",
                    help="redact local paths and client identities before embedding")
    ap.add_argument("--no-fragment", action="store_true",
                    help="skip the artifact fragment companion file")
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    ba_path = Path(args.before_after)
    ba = json.loads(ba_path.read_text(encoding="utf-8")) if ba_path.exists() else {"repos": []}

    if args.public:
        data, ba, redacted = sanitize(data, ba)
        print(f"public mode: {redacted} client projects anonymised, "
              f"all local paths removed")

    script = (SCRIPT
              .replace("__DATA__", json.dumps(data, separators=(",", ":")))
              .replace("__BA__", json.dumps(ba, separators=(",", ":"))))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        + META + HEAD + "</head>\n<body>\n" + BODY + script + "</body>\n</html>\n",
        encoding="utf-8",
    )
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")

    if not args.no_fragment:
        frag = out.with_suffix(".fragment.html")
        frag.write_text(HEAD + BODY + script, encoding="utf-8")
        print(f"wrote {frag} ({frag.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
