import re
from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

import odoo.addons

# Font Awesome 7 renders `content: var(--fa)/""`, so a class name it does not
# define produces no glyph at all rather than a visible fallback box. A typo, or
# an FA4 name that outlived its shim, is therefore an icon that silently stops
# rendering — three of them were live when this test was written. Every FA4 name
# still in the tree survives only through the hand-written v4-shims.css, so the
# drift this guards against is real and ongoing.

FA_CSS_DIR = "web/static/src/libs/fontawesome7/css"

RE_DEFINED = re.compile(r"\.(fa-[a-z0-9-]+)")
RE_CLASS_ATTR = re.compile(r'\b(?:t-att-class|t-attf-class|class)\s*=\s*"([^"]*)"')
RE_FA_TOKEN = re.compile(r"^fa-[a-z0-9-]+$")

# Names that look like Font Awesome classes but are owned by something else.
NON_FA_CLASSES = {
    # defined by the vendored o_spreadsheet bundle, which injects its own CSS
    # (see the `.fa-small` rule inside o_spreadsheet.js)
    "fa-small",
}


class TestFontAwesomeIconNames(odoo.tests.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # the addons directory of this repository, which owns the stylesheets
        cls.addons_root = Path(file_path("web/__manifest__.py")).parent.parent
        cls.fa_css_dir = cls.addons_root / FA_CSS_DIR
        cls.scanned_roots = cls._addons_roots()

    @classmethod
    def _addons_roots(cls):
        """Every addons directory the running server loads, not just this repo.

        A spliced class name in an *enterprise* template
        (``'fa-solid fa-angle- fa-2x' + (opened ? 'up' : 'down')``, from the FA4→7
        upgrade) rendered no chevron and cost 14 barcode tour failures. It was
        invisible to this guard purely because the scan stopped at this
        repository, while the icons it validates are shipped from here for every
        addon on the path. CI checks this repo out alone, so there the scanned
        set is unchanged; a workspace that assembles siblings gets them covered.
        """
        roots, seen = [], set()
        for path in [str(cls.addons_root), *odoo.addons.__path__]:
            resolved = Path(path).resolve()
            if resolved.is_dir() and resolved not in seen:
                seen.add(resolved)
                roots.append(resolved)
        return roots

    def _defined_class_names(self):
        """Every `.fa-*` selector the shipped stylesheets define: icons, the
        utility classes (sizes, spin, stack, ...) and the FA4 shims."""
        names = set()
        for css in sorted(self.fa_css_dir.glob("*.css")):
            names |= set(RE_DEFINED.findall(css.read_text(encoding="utf-8")))
        return names

    def _used_class_names(self):
        """`fa-*` tokens written literally in a template class attribute, mapped
        to the files using them. Attributes holding an interpolation are skipped:
        their value is only known at render time.

        A concatenated name is *not* an interpolation and is still checked: the
        dangling half of ``'fa-solid fa-angle- fa-2x' + (…)`` reads as the token
        ``fa-angle-``, which no stylesheet defines — which is exactly how that
        bug announces itself here.
        """
        used = {}
        for root in self.scanned_roots:
            for path in root.rglob("*.xml"):
                if self.fa_css_dir in path.parents:
                    continue
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if "fa-" not in content:
                    continue
                for value in RE_CLASS_ATTR.findall(content):
                    if any(c in value for c in "{}#$"):
                        continue
                    for token in value.split():
                        if RE_FA_TOKEN.match(token):
                            used.setdefault(token, set()).add(
                                str(path.relative_to(root))
                            )
        return used

    def test_fontawesome_stylesheets_are_present(self):
        """Guards the guard: a moved or renamed vendor drop must not turn this
        test into a no-op that reports success against an empty name set."""
        self.assertTrue(self.fa_css_dir.is_dir(), f"missing {FA_CSS_DIR}")
        defined = self._defined_class_names()
        self.assertGreater(len(defined), 4000, "font awesome css looks truncated")
        for expected in ("fa-solid", "fa-spin", "fa-trash", "fa-star-o"):
            self.assertIn(expected, defined)

    def test_every_icon_class_used_in_a_template_is_defined(self):
        defined = self._defined_class_names() | NON_FA_CLASSES
        used = self._used_class_names()
        self.assertGreater(len(used), 100, "icon scan found suspiciously little")
        undefined = {
            name: sorted(files) for name, files in used.items() if name not in defined
        }
        self.assertFalse(
            undefined,
            "these icon classes render no glyph because no stylesheet defines "
            "them — fix the name, or add it to NON_FA_CLASSES if another "
            "library owns it:\n"
            + "\n".join(
                f"  {name}: {', '.join(files)}"
                for name, files in sorted(undefined.items())
            ),
        )
