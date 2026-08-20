"""What a document writes into its own chatter.

Named for what it protects, not for the review that produced it.
"""

from odoo.orm.runtime import environment as environment_module
from odoo.tests.common import tagged
from odoo.tools import translate as translate_tools

from .test_documents_common import GIF, TransactionCaseDocuments


@tagged("post_install", "-at_install")
class TestDocumentsTrashChatterTranslation(TransactionCaseDocuments):
    """The trash/restore messages resolve their own module and language."""

    def test_transition_messages_resolve_their_module_and_language(self):
        """`_()` inside a lambda resolves neither module nor language.

        The frame it inspects for a ``self``/``env``/``cr`` is the lambda's,
        which has none, so off any HTTP request -- crons, the mail gateway, the
        archive cascade of `mixin.documents.unlink`, this test -- it fell back
        to ``("base", "en_US")`` and logged a WARNING with a full stack trace
        for every parent folder it posted to.

        Asserted in French on purpose: ``en_US`` short-circuits to
        ``("base", "en_US")`` by design in both implementations, so an English
        run cannot tell the fix from the bug.
        """
        self.env["res.lang"]._activate_lang("fr_FR")
        document = self.env["documents.document"].create(
            {
                "type": "binary",
                "name": "translated trash",
                "datas": GIF,
                "folder_id": self.folder_b.id,
                "owner_id": self.doc_user.id,
            }
        )
        self.env.flush_all()

        seen = []

        def make_spy(original):
            def spy(module, lang, source, args=None):
                seen.append((module, lang, source))
                return original(module, lang, source, args)

            return spy

        # Both namespaces: `Environment._` holds its own reference to
        # `get_translation`, imported by name, so patching only the tools
        # module would watch the wrong door.
        self.patch(
            translate_tools,
            "get_translation",
            make_spy(translate_tools.get_translation),
        )
        self.patch(
            environment_module,
            "get_translation",
            make_spy(environment_module.get_translation),
        )
        document.with_context(lang="fr_FR").action_archive()

        resolved = {
            (module, lang) for module, lang, source in seen if "sent to trash" in source
        }
        self.assertTrue(resolved, "the trash message must be looked up at all")
        self.assertEqual(
            resolved,
            {("documents", "fr_FR")},
            "under ('base', 'en_US') no .po entry of this module could match",
        )
