"""Differential characterization of the ``user_permission`` algebra.

``documents.document.user_permission`` is implemented **twice**: once in Python
(``_compute_user_permission`` -> ``_get_permission_without_token_multi``) and
once as domain algebra (``_search_user_permission``, which is what every record
rule in ``security.xml`` ultimately evaluates). Nothing forces the two to agree,
and every disagreement is a security-relevant bug in one direction or the other:

* compute says ``none`` / search matches   -> the record is invisible in the UI
  but reachable through search, export, ``read_group``, or a related field.
* compute says ``edit`` / search misses    -> the UI offers actions the ORM then
  refuses, and the record vanishes from its own list view.

This module enumerates the state space both implementations branch on and
asserts they agree on every cell, for every kind of user. It is what found the
two divergences that the unification then removed.

**Since the unification, `_compute_user_permission` is derived from
`_search_user_permission`**, so the agreement assertion no longer cross-checks
two algorithms. Read honestly, it now guards:

* the derivation plumbing -- unsaved records, archived documents, the
  reachable/editable split -- which is easy to get wrong and invisible in
  ordinary tests;
* the *partition* property (a document is never both "view" and "edit"), which
  is a property of the domain alone and was violated before;
* re-divergence, should anyone reintroduce a Python path.

`test_permission_never_undercuts_the_token_less_level` keeps a genuine
cross-check alive against the one independent implementation that survives,
`_get_permission_without_token_multi`.
"""

from odoo import Command, fields
from odoo.tests.common import TransactionCase, tagged

# Membership states the algebra distinguishes, as
# ``role, expiration_offset_days`` (None = no ``documents.access`` row at all;
# a row with ``role=False`` is the access *log* row the module writes on read).
MEMBERSHIPS = {
    "absent": None,
    "log_only": (False, None),
    "view": ("view", None),
    "edit": ("edit", None),
    "view_expired": ("view", -1),
}
ACCESS_LEVELS = ("none", "view", "edit")


@tagged("post_install", "-at_install")
class TestPermissionAlgebraDifferential(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env["res.users"]
        cls.company_main = cls.env.company
        cls.company_other = cls.env["res.company"].create({"name": "Algebra Other Co"})

        def user(login, group):
            return Users.create(
                {
                    "name": login,
                    "login": login,
                    "group_ids": [Command.link(cls.env.ref(group).id)],
                    "company_id": cls.company_main.id,
                    "company_ids": [Command.set(cls.company_main.ids)],
                }
            )

        cls.user_system = user("algebra_system", "documents.group_documents_system")
        cls.user_manager = user("algebra_manager", "documents.group_documents_manager")
        cls.user_internal = user("algebra_internal", "documents.group_documents_user")
        cls.user_portal = user("algebra_portal", "base.group_portal")
        cls.user_public = cls.env.ref("base.public_user")
        cls.user_other = user("algebra_other", "documents.group_documents_user")

        # Subjects that may hold a membership. The public partner is excluded on
        # purpose: `documents.access._check_partner_id` forbids giving it a role
        # (anonymous sharing goes through `access_via_link`).
        cls.member_subjects = (
            cls.user_system | cls.user_manager | cls.user_internal | cls.user_portal
        )
        cls.subjects = cls.member_subjects | cls.user_public

        cls.matrix = cls.env["documents.document"]
        cls._build_root_matrix()
        cls._build_owned_matrix()
        cls._build_folder_matrix()
        cls._build_shortcut_matrix()
        cls.matrix.flush_recordset()

    # ------------------------------------------------------------------
    # matrix construction
    # ------------------------------------------------------------------
    @classmethod
    def _membership_commands(cls, membership):
        """Grant the same membership state to every subject at once.

        Permission is evaluated per partner, so giving all subjects the
        identical row lets one document serve as the same cell of the matrix for
        each of them.
        """
        spec = MEMBERSHIPS[membership]
        if spec is None:
            return []
        role, offset = spec
        expiration = (
            fields.Datetime.add(fields.Datetime.now(), days=offset) if offset else False
        )
        return [
            Command.create(
                {
                    "partner_id": subject.partner_id.id,
                    "role": role,
                    "expiration_date": expiration,
                    # the constraint requires one of role / last_access_date
                    "last_access_date": fields.Datetime.now() if not role else False,
                }
            )
            for subject in cls.member_subjects
        ]

    @classmethod
    def _create(cls, **vals):
        document = cls.env["documents.document"].create({"type": "binary", **vals})
        cls.matrix |= document
        return document

    @classmethod
    def _build_root_matrix(cls):
        """Documents at a drive root: owner x internal x link x membership x company."""
        for owner in (cls.user_other, cls.env["res.users"]):
            for access_internal in ACCESS_LEVELS:
                for access_via_link in ACCESS_LEVELS:
                    for membership in MEMBERSHIPS:
                        for company in (
                            cls.env["res.company"],
                            cls.company_main,
                            cls.company_other,
                        ):
                            cls._create(
                                name=f"root/{owner.id}/{access_internal}/"
                                f"{access_via_link}/{membership}/{company.id}",
                                owner_id=owner.id,
                                company_id=company.id,
                                access_internal=access_internal,
                                access_via_link=access_via_link,
                                access_ids=cls._membership_commands(membership),
                            )

    @classmethod
    def _build_owned_matrix(cls):
        """The "I own it" cell, which the shared matrix cannot express.

        Share users are skipped: `_check_root_documents_owner_id` forbids them
        owning a document at a drive root.
        """
        for subject in cls.member_subjects.filtered(lambda user: not user.share):
            for access_internal in ACCESS_LEVELS:
                for access_via_link in ACCESS_LEVELS:
                    cls._create(
                        name=f"owned/{subject.login}/{access_internal}/{access_via_link}",
                        owner_id=subject.id,
                        access_internal=access_internal,
                        access_via_link=access_via_link,
                    )

    @classmethod
    def _build_folder_matrix(cls):
        """Link access granted one level up, and its `hidden` opt-out.

        The parent is varied over every way it can be reachable -- internal
        access, membership, and ownership -- because the child's link is granted
        on the strength of the parent being reachable *at all*, not at any
        particular level.
        """
        parents = [
            (
                f"internal-{parent_internal}",
                {"access_internal": parent_internal},
            )
            for parent_internal in ACCESS_LEVELS
        ]
        parents += [
            (
                "member-view",
                {
                    "access_internal": "none",
                    "access_ids": cls._membership_commands("view"),
                },
            ),
            (
                "member-edit",
                {
                    "access_internal": "none",
                    "access_ids": cls._membership_commands("edit"),
                },
            ),
        ]
        parents += [
            (
                f"owned-by-{subject.login}",
                {"access_internal": "none", "owner_id": subject.id},
            )
            for subject in cls.member_subjects.filtered(lambda user: not user.share)
        ]

        for label, parent_vals in parents:
            folder = cls._create(
                name=f"folder/{label}",
                type="folder",
                access_via_link="none",
                **parent_vals,
            )
            for access_via_link in ACCESS_LEVELS:
                for hidden in (False, True):
                    cls._create(
                        name=f"child/{label}/{access_via_link}/{hidden}",
                        folder_id=folder.id,
                        access_internal="none",
                        access_via_link=access_via_link,
                        is_access_via_link_hidden=hidden,
                    )

    @classmethod
    def _build_shortcut_matrix(cls):
        """Shortcuts, whose permission is partly borrowed from their target."""
        for target_internal in ACCESS_LEVELS:
            for target_link in ACCESS_LEVELS:
                target = cls._create(
                    name=f"target/{target_internal}/{target_link}",
                    owner_id=cls.user_other.id,
                    access_internal=target_internal,
                    access_via_link=target_link,
                )
                for shortcut_owner in (cls.user_other, cls.env["res.users"]):
                    cls._create(
                        name=f"shortcut/{target_internal}/{target_link}/{shortcut_owner.id}",
                        shortcut_document_id=target.id,
                        owner_id=shortcut_owner.id,
                        access_internal=target_internal,
                        access_via_link=target_link,
                    )
        for subject in cls.member_subjects.filtered(lambda user: not user.share):
            target = cls._create(
                name=f"target-owned/{subject.login}",
                owner_id=cls.user_other.id,
                access_internal="view",
                access_via_link="none",
            )
            cls._create(
                name=f"shortcut-owned/{subject.login}",
                shortcut_document_id=target.id,
                owner_id=subject.id,
                access_internal="view",
                access_via_link="none",
            )

    # ------------------------------------------------------------------
    # the differential itself
    # ------------------------------------------------------------------
    def _computed(self, subject):
        """What `_compute_user_permission` says, for every cell.

        Read in ``sudo`` so that cells computing to ``none`` -- which the record
        rule would refuse to even read -- are still observable. ``sudo`` does not
        change the answer: the compute keys off ``self.env.user`` and
        ``self.env.companies``, which ``sudo()`` leaves untouched.
        """
        documents = self.matrix.with_user(subject).sudo()
        documents.invalidate_recordset(["user_permission"])
        return {document.id: document.user_permission for document in documents}

    def _searched(self, subject, level):
        """What `_search_user_permission` matches, for the same cells.

        ``sudo`` only to get past the model-level ACL (the public user has none
        on ``documents.document``); the field's search method still runs as
        ``subject``, which is what is under test. Record rules are themselves
        expressed on ``user_permission``, so dropping them removes a tautology
        rather than a constraint.
        """
        return set(
            self.env["documents.document"]
            .with_user(subject)
            .sudo()
            .search([("id", "in", self.matrix.ids), ("user_permission", "in", [level])])
            .ids
        )

    def _assert_implementations_agree(self, subject):
        computed = self._computed(subject)
        edit_ids = self._searched(subject, "edit")
        view_ids = self._searched(subject, "view")

        disagreements = []
        for document_id, computed_level in computed.items():
            searched_level = (
                "edit"
                if document_id in edit_ids
                else "view"
                if document_id in view_ids
                else "none"
            )
            if computed_level != searched_level:
                disagreements.append(
                    (
                        self.matrix.browse(document_id).name,
                        computed_level,
                        searched_level,
                    )
                )

        if disagreements:
            lines = "\n".join(
                f"  {name}: compute={computed_level!r} search={searched_level!r}"
                for name, computed_level, searched_level in sorted(disagreements)
            )
            self.fail(
                f"{len(disagreements)}/{len(computed)} cells disagree for "
                f"{subject.login}:\n{lines}"
            )

        # Secondary, and reported only once the levels agree: the two searched
        # sets must partition. A document answering both `user_permission =
        # 'view'` and `= 'edit'` shows up in mutually exclusive filters at once.
        if both := edit_ids & view_ids:
            names = "\n".join(
                f"  {name}" for name in sorted(self.matrix.browse(both).mapped("name"))
            )
            self.fail(
                f"{len(both)} cells match both 'view' and 'edit' for "
                f"{subject.login}:\n{names}"
            )

    def test_matrix_is_populated(self):
        """Guard against the matrix silently collapsing to a handful of rows."""
        self.assertGreater(len(self.matrix), 300)

    def test_agreement_for_system_administrator(self):
        self._assert_implementations_agree(self.user_system)

    def test_agreement_for_documents_manager(self):
        self._assert_implementations_agree(self.user_manager)

    def test_agreement_for_internal_user(self):
        self._assert_implementations_agree(self.user_internal)

    def test_agreement_for_portal_user(self):
        self._assert_implementations_agree(self.user_portal)

    def test_agreement_for_public_user(self):
        self._assert_implementations_agree(self.user_public)

    def test_permission_never_undercuts_the_token_less_level(self):
        """Cross-check against the one independent implementation left.

        `_get_permission_without_token_multi` still answers a narrower question
        in Python -- "what would this user have without following a share link"
        -- and the controllers rely on it. The full algebra only ever *adds*
        grants on top of it (a link, a link inherited from the parent, the
        shortcut-owner extension), so the level it reports must never exceed the
        one `user_permission` reports. A drift in either direction shows up here.
        """
        ranking = {"none": 0, "view": 1, "edit": 2}
        for subject in self.subjects:
            documents = self.matrix.with_user(subject).sudo()
            documents.invalidate_recordset(["user_permission"])
            token_less = documents._get_permission_without_token_multi()
            undercut = [
                (document.name, without_token, document.user_permission)
                for document, without_token in token_less.items()
                if ranking[without_token] > ranking[document.user_permission]
            ]
            self.assertFalse(
                undercut,
                f"{subject.login}: user_permission is weaker than the "
                f"token-less level for:\n"
                + "\n".join(
                    f"  {name}: without_token={without_token!r} "
                    f"user_permission={permission!r}"
                    for name, without_token, permission in sorted(undercut)
                ),
            )

    def test_every_divergence_traces_to_a_known_blind_spot(self):
        """State the divergence *positively*, not just as an inequality.

        `test_permission_never_undercuts_the_token_less_level` above only pins
        `token_less <= user_permission`, so the two implementations can drift
        anywhere inside that band without anything noticing -- which is exactly
        the room a downstream override needs to get it wrong.

        Enumerating the matrix gives the band a precise shape. The token-less
        level is blind to exactly three grants, and every divergence is
        attributable to one of them:

        * the **share link** on the document itself -- the link IS the token, so
          being blind to it is the whole point;
        * the **system-administrator** blanket grant, which
          `_search_user_permission` short-circuits on and the Python side does
          not implement at all;
        * the **shortcut-owner extension**, where owning a shortcut to a
          document you may only view still grants edit (the Python side sets
          `exclude_ownership` for shortcuts).

        A divergence outside that set means one implementation has grown a rule
        the other lacks -- the failure mode this whole file exists to catch.
        """
        ranking = {"none": 0, "view": 1, "edit": 2}
        unexplained = []
        divergent_cells = 0
        for subject in self.subjects:
            is_system = subject.has_group("documents.group_documents_system")
            documents = self.matrix.with_user(subject).sudo()
            documents.invalidate_recordset(["user_permission"])
            token_less = documents._get_permission_without_token_multi()
            for document, without_token in token_less.items():
                permission = document.user_permission
                if without_token == permission:
                    continue
                divergent_cells += 1
                self.assertLess(
                    ranking[without_token],
                    ranking[permission],
                    f"{subject.login}/{document.name}: a divergence may only "
                    "ever be an upgrade",
                )
                explained = (
                    is_system
                    or document.access_via_link != "none"
                    or bool(document.shortcut_document_id)
                )
                if not explained:
                    unexplained.append(
                        (subject.login, document.name, without_token, permission)
                    )

        self.assertFalse(
            unexplained,
            "these cells diverge without a link, system rights or a shortcut to "
            "explain it, so the two implementations have genuinely drifted:\n"
            + "\n".join(map(str, unexplained)),
        )
        # Guard the guard: with no divergence at all the assertion above passes
        # vacuously and pins nothing.
        self.assertTrue(
            divergent_cells,
            "no divergence found at all -- the matrix no longer exercises any "
            "of the three blind spots, so this test proves nothing",
        )

    # ------------------------------------------------------------------
    # the two divergences this net found, stated in user-visible terms
    # ------------------------------------------------------------------
    def test_link_shared_child_is_searchable_at_the_level_the_link_grants(self):
        """A Viewer folder holding an Editor link: the child is editable.

        The search used to require the *parent* to match the level being
        searched, so this document computed to `edit` but answered neither
        `user_permission = 'edit'` nor `= 'view'`. It was therefore skipped by
        every level-specific domain -- including `_get_access_update_domain()`,
        which decides what an access-rights propagation is allowed to touch.
        """
        Document = self.env["documents.document"]
        folder = Document.create(
            {"name": "Viewer folder", "type": "folder", "access_internal": "view"}
        )
        child = Document.create(
            {
                "name": "Editor link child",
                "type": "binary",
                "folder_id": folder.id,
                "access_internal": "none",
                "access_via_link": "edit",
                "is_access_via_link_hidden": False,
            }
        )
        as_user = Document.with_user(self.user_internal)

        self.assertEqual(child.with_user(self.user_internal).user_permission, "edit")
        self.assertIn(
            child.id,
            as_user.sudo().search([("user_permission", "=", "edit")]).ids,
            "a document the user can edit must be findable as editable",
        )
        self.assertNotIn(
            child.id, as_user.sudo().search([("user_permission", "=", "view")]).ids
        )

    def test_owned_document_is_not_reported_as_view_only(self):
        """Ownership beats `access_internal`, so an owner is never a viewer.

        `= 'view'` matched on the `access_internal = 'view'` clause alone, so a
        document the user owns (and computes `edit` on) also answered the
        "Viewer" filter -- appearing in two mutually exclusive filters at once.
        """
        Document = self.env["documents.document"]
        owned = Document.create(
            {
                "name": "Mine but internally view",
                "type": "binary",
                "owner_id": self.user_internal.id,
                "access_internal": "view",
                "access_via_link": "view",
            }
        )
        as_user = Document.with_user(self.user_internal)

        self.assertEqual(owned.with_user(self.user_internal).user_permission, "edit")
        self.assertIn(
            owned.id, as_user.sudo().search([("user_permission", "=", "edit")]).ids
        )
        self.assertNotIn(
            owned.id,
            as_user.sudo().search([("user_permission", "=", "view")]).ids,
            "an owner must not show up under the Viewer filter",
        )
