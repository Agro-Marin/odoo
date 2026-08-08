# IoT Box image

Build tooling for the Raspberry Pi IoT Box image. `installable: False` — this
module is never loaded by a server; `build_image.sh` reads it to assemble an
`.img`.

## What lands on the box

`build_utils/sparse-checkout` is the authoritative list, and it puts **the whole
`odoo/` framework plus `odoo-bin`** on the box, not just the driver addons. The
box therefore runs a real server process (`overwrite_before_init/etc/systemd/
system/odoo.service` → `/usr/bin/python3 /home/pi/odoo/odoo-bin`), configured by
`configuration/odoo.conf` with `server_wide_modules = iot_drivers,web` and no
database.

That is the fact behind everything below: **the box needs the framework's own
dependencies, not only the drivers'.** The conf naming only `iot_drivers,web`
does not narrow this — `tools/config.py:37` defines
`REQUIRED_SERVER_WIDE_MODULES = ["base", "web"]` and prepends whichever is
missing, so `base` always loads. Measured, on this tree:

```python
load_odoo_module("base")   # → weasyprint, cssselect2, lxml, psycopg all imported
```

So an unguarded module-level import anywhere in `odoo/` or `odoo/addons/base/`
is a hard requirement here, and a missing one is a boot failure rather than a
degraded feature.

Three paths in the sparse-checkout matched nothing in this fork and were dropped
on 2026-08-08 — `addons/hw_drivers`, `addons/hw_posbox_homepage` and
`addons/point_of_sale/tools/posbox/configuration`. Upstream's `hw_*` pair was
consolidated into `iot_drivers`/`iot_base` here. Git ignores a pattern that
matches nothing, so they were silent, not broken.

## Where a dependency goes: apt or pip

| File | Installed by | Carries |
|---|---|---|
| `configuration/packages.txt` | `xargs apt-get install` (`init_image.sh:160`, and `iot_drivers/tools/upgrade.py:188` on-box) | anything Debian packages |
| `configuration/requirements.txt` | `pip3 install -r … --break-system-package` | what Debian does not package, or what needs a version Debian does not carry |

**`packages.txt` cannot contain comments.** It is fed to `xargs`, which would
pass a `#` through as a package name and fail the install. Record the reasoning
here or in `requirements.txt` (pip does accept `#`), never in that file.

Both lists are checked against the tree by reading what the sparse-checkout
actually ships and keeping only *unguarded, module-level* imports. A dependency
behind `try/except ImportError` or `find_spec` — `blake3`, `python-magic`,
`geoip2`, `vobject`, `zeep` — degrades rather than crashing, so it is optional
here even when it is pinned for the server.

### Corrected 2026-08-08

Both lists had drifted from what the fork imports:

* `python3-psycopg2` → `python3-psycopg` + `python3-psycopg-pool`. This fork uses
  **psycopg 3 exclusively** (`odoo/db/` imports `psycopg`, 67 files); psycopg2 is
  not installed anywhere and cannot satisfy it.
* `python3-pypdf2` → `python3-pypdf`. PyPDF2 is the dead predecessor and a
  different import name; `odoo/tools/pdf/_pypdf.py` imports `pypdf`.
* `python3-jinja2` removed. It was a fossil of upstream's `hw_posbox_homepage`,
  which rendered the status pages through Jinja templates. This fork serves
  static `index.html`/`logs.html`/`status_display.html` and renders with OWL
  (`iot_drivers/controllers/homepage.py`), so nothing on the box imports it —
  `odoo/cli/scaffold.py` is the only consumer left in the tree, and the box never
  runs `odoo-bin scaffold`.
* Added, all unguarded imports in shipped code that no list carried: `lxml`
  (40 files), `markupsafe` (18), `orjson`, `idna`, `bs4`, `cssselect2`,
  `xlsxwriter`, `asn1crypto`.
* `weasyprint` added to `requirements.txt`, because there is **no
  `python3-weasyprint` in any Debian suite** and
  `base/models/ir_actions_report.py` imports it at module level.

## Two blockers: this image cannot run the fork today

Neither is fixable by editing a dependency list. Both are recorded here so the
lists are not mistaken for a working configuration.

**1. Python floor.** `odoo/release.py` sets `MIN_PY_VERSION = (3, 14)` and
`odoo/init.py:9` raises `RuntimeError` below it. The base image
`download_requirements.sh` fetches is `raspios_lite_armhf` **bookworm**, whose
`python3` is 3.11.2 — and `odoo.service` runs `/usr/bin/python3`, the system
interpreter. No current Debian stable clears the bar:

| Suite | `python3` | vs floor |
|---|---|---|
| bookworm (what we build on) | 3.11.2 | too old |
| trixie | 3.13.5 | too old |
| sid | 3.14.6 | meets it |

So this needs a newer base image *and* a suite that is not yet stable, or a
Python 3.14 built into the image. Note the same move fixes a second problem:
bookworm's `python3-psycopg` is 3.1.7 and trixie's 3.2.6, both below the
server's `psycopg[binary]>=3.3.4` floor — only sid's 3.3.4 satisfies it.

**2. `odoo_rust`.** `odoo/init.py:18` imports it as a hard dependency with no
fallback, and nothing in the image build produces or installs it. The freshness
check below that import is *not* the obstacle — it is skipped when `crates/` is
absent (`init.py:53`), which is exactly the box's case — so the box needs only a
prebuilt wheel, not the crate sources.

There is no armhf wheel on PyPI; it is this fork's own crate, so one has to be
cross-compiled and shipped. The mechanism already exists in this directory:
`configuration/aiortc-1.4.0-py3-none-any.whl` is vendored and referenced by
absolute path from `requirements.txt`. An `odoo_rust` wheel would follow the same
pattern, and must be rebuilt whenever `crates/odoo_rust` changes.
