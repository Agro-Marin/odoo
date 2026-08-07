import inspect
import re

from odoo.tests import common

COPY_MIXIN = "orm/models/mixins/copy.py"
MARKER_RE = re.compile(r"""['"]([^'"]*\(copy\)[^'"]*)['"]""")


@common.tagged("post_install", "-at_install")
@common.no_retry
class TestCopyTranslations(common.TransactionCase):
    @staticmethod
    def _source(method):
        try:
            return inspect.getsource(method)
        except OSError, TypeError:
            return ""

    @classmethod
    def _renamed_translated_fields(cls, model):
        translated = {
            name
            for name, field in model._fields.items()
            if field.translate is True and field.store
        }
        if not translated:
            return set(), set()
        renamed, markers = set(), set()
        for klass in model.__mro__:
            copy_data = vars(klass).get("copy_data")
            if copy_data is None:
                continue
            source = cls._source(copy_data)
            if "(copy)" not in source:
                continue
            renamed |= {name for name in translated if name in source}
            markers |= set(MARKER_RE.findall(source))
        return renamed, markers

    def test_renamed_translated_field_has_copy_translations(self):
        offenders = []
        for model_name, model in self.env.registry.items():
            renamed, _markers = self._renamed_translated_fields(model)
            if not renamed:
                continue
            try:
                source_file = inspect.getsourcefile(model.copy_translations) or ""
            except TypeError:
                source_file = ""
            if COPY_MIXIN in source_file:
                offenders.append(f"{model_name} ({', '.join(sorted(renamed))})")

        self.assertFalse(
            sorted(offenders),
            "these models rename a translated field in copy_data without a "
            "matching copy_translations override; add one calling "
            "BaseModel._copy_translations_of_renamed_field so every language "
            "gets its own marked term",
        )

    def test_copy_translations_reuses_the_copy_data_marker(self):
        offenders = []
        for model_name, model in self.env.registry.items():
            renamed, markers = self._renamed_translated_fields(model)
            if not renamed or not markers:
                continue
            override = self._source(model.copy_translations)
            if COPY_MIXIN in (inspect.getsourcefile(model.copy_translations) or ""):
                continue
            used = set(MARKER_RE.findall(override))
            if not used & markers:
                offenders.append(
                    f"{model_name}: copy_data uses {sorted(markers)}, "
                    f"copy_translations uses {sorted(used)}"
                )

        self.assertFalse(
            sorted(offenders),
            "the marker in copy_translations must match the one copy_data "
            "applies, otherwise the override silently does nothing",
        )
