"""Server-side asset pipeline (Odoo-coupled).

The Python side of the JavaScript asset bundler: esbuild orchestration, the ESM
module graph, bridge-shim generation, and the manifest-driven ESM bundle
registry. These modules are framework-aware (they use odoo.api, odoo.modules,
odoo.tools, odoo.addons) and therefore live under tools/ rather than the
dependency-free odoo/libs/ (see ADR-0004). They build on the dependency-free
helpers that remain in libs/ (odoo.libs.asset_log, odoo.libs.constants).
"""
