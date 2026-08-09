"""Tag names are unique on the source term, not the translation document."""

from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestTagNameUniqueness(TestProjectCommon):
    def test_translated_tag_name_is_still_unique(self) -> None:
        """``name`` is translate=True, so it is jsonb and a plain UNIQUE(name)
        compared whole translation documents: once a second language existed,
        two tags could share an English name."""
        self.env["res.lang"]._activate_lang("fr_FR")
        tag = self.env["project.tags"].create({"name": "Uniqueness"})
        tag.with_context(lang="fr_FR").name = "Unicite"
        self.env.flush_all()

        with self.assertRaises(Exception):
            self.env["project.tags"].create({"name": "Uniqueness"})
            self.env.flush_all()
