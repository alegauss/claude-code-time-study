# Improvements

## Block A — On the design system

### §TS1 The report on the design system

`docs/index.html` is 116 KB and 1,547 lines, with one `<style>` block of 194 lines (37
to 232): its own tokens (`--page`, `--surface`, `--ink`, `--muted`, `--border`) in
light, dark and both `data-theme` overrides, then the header, cards, tables and footer.
The page is not written by hand: `build.cmd` runs `build_report.py --out
docs\index.html`, and the CSS lives in that script's template (lines 22 to 217). The
change goes there, and the page is rebuilt from it.

The move links `tokens.css` and `site.css` (VDS216) from jsDelivr at a pinned version
and sets `data-tone="warm"`: the light ground is `#f9f9f7`, an off-white with no blue in
it. The accent comes from `projects.json`, `47,184,148` with `#5BD4B4` bright. The
inline CSS those two files cover goes; what stays is page-specific: the chart series
(`--s1`..`--s6`), `--grid` and `--axis`, and the measured and assumed tags.

The Google Analytics tag is in `docs/index.html` only (`23c3d9e`), not in
`build_report.py`, so the next `build.cmd` run drops it. The template gains it, loaded
only after consent as the hub's AG1 does, and `verify_public.py` keeps passing.

Done when no CSS that `site.css` provides is left in the template or the page, the text
of the rebuilt page is unchanged, light and dark screenshots are compared before and
after with the differences listed in the commit, and the page is listed in
`consumers.json` through VDS217.
