# Vendored libraries

Third-party libraries shipped inside the `web` module. **Do not edit these files** — replace the directory wholesale when updating to a new upstream release.

Each subdirectory contains a `VERSION.txt` with the upstream version string (or `internal` for libraries developed inside the fork).

## Inventory

| Directory | Version | Source / notes |
|-----------|---------|----------------|
| `ace/` | 1.43.6 | https://ajaxorg.github.io/ace/ — `exports.version` in `ace.js` |
| `bootstrap/` | 5.3.8 | https://getbootstrap.com — header comment in `bootstrap.esm.js` |
| `Chart/` | 4.5.1 | https://www.chartjs.org — header comment in `Chart.js` (bundled with `@kurkle/color v0.3.2`) |
| `chartjs-adapter-luxon/` | 1.3.1 | https://github.com/chartjs/chartjs-adapter-luxon |
| `diff_match_patch/` | forked | Trimmed fork of https://github.com/google/diff-match-patch (diff functions only). See header comment in `diff_match_patch.js` for the modifications applied. |
| `dompurify/` | 3.3.1 | https://github.com/cure53/DOMPurify |
| `fullcalendar/` | 7.0.0-rc.3 | https://fullcalendar.io — header comment in `fullcalendar.global.js`. Single-bundle Vanilla JS distribution (core + interaction + daygrid + timegrid + list + multimonth) plus `skeleton.css` and `locales-all.global.js`. |
| `hoot/` | internal | Odoo HOOT test framework — versioned with the fork |
| `hoot-dom/` | internal | Odoo HOOT DOM helpers — versioned with the fork |
| `luxon/` | 3.7.2 | https://moment.github.io/luxon/ — `VERSION` constant in `luxon.js` |
| `odoo_ui_icons/` | 1.2 | Odoo UI icon font (built with IcoMoon, sourced from Carbon + Material) — see `Read Me.txt` |
| `owl/` | internal | OWL component framework — versioned with the fork |
| `pdfjs/` | 4.8.69 | https://mozilla.github.io/pdf.js/ — `pdfjsVersion` constant in `build/pdf.js` |
| `popper/` | 2.11.8 | https://popper.js.org — `@popperjs/core` |
| `prismjs/` | 1.30.0 | https://prismjs.com — header comment in `prism.js` |
| `qunit/` | 2.9.1 | https://qunitjs.com — version in filename |
| `signature_pad/` | 5.1.3 | https://github.com/szimek/signature_pad |
| `stacktracejs/` | 2.0 (verify) | https://www.stacktracejs.com — minified, no inline version marker; verify against upstream before updating |
| `zxing-library/` | 0.21.3 | https://github.com/zxing-js/library — see `version` file |

## Update procedure

1. **Confirm the new version is needed.** Pin upgrades to a real reason (security CVE, required feature, license clarity). Do not chase versions for their own sake — every update churns the diff and risks bundle-size regressions.
2. **Replace the directory wholesale.** `rm -rf static/lib/<lib>/<files>` then drop in the new release. Do not patch in place.
3. **Update `VERSION.txt`** in the same commit with the new upstream version string.
4. **Update this README's inventory table** with the new version + source pointer.
5. **Re-run `--test-tags=web_assets -u web`** to confirm bundle generation still succeeds.
6. **Smoke-test the surfaces that consume the lib** (e.g. updating `Chart/` requires loading a graph view; updating `pdfjs/` requires opening a PDF in the file viewer).
7. **Check the LICENSE.** If the upstream license changed, surface it in the PR description.

## Notes

- Libraries marked `internal` (`owl/`, `hoot/`, `hoot-dom/`) are developed inside the fork. Their version is the Odoo version itself; they evolve with the rest of the codebase rather than tracking an external upstream.
- `VERSION.txt` files are intentionally minimal (single line, no frontmatter) so they remain easy to read with `cat` and easy to grep across the tree (`find static/lib -name VERSION.txt -exec sh -c 'echo "$1: $(cat "$1")"' _ {} \;`).
- For licensing audits, the per-lib `LICENSE` / `LICENSE.md` file is authoritative when present.
