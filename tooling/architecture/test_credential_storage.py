from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import credential_storage as gate

MODEL = """
from odoo import fields, models


class Thing(models.{base}):
    _name = "thing"

    {field}
"""


def _write(tmp_path, monkeypatch, field, base="Model", allowed=None, module="carrier"):
    root = tmp_path / "addons"
    (root / module / "models").mkdir(parents=True)
    (root / module / "__manifest__.py").write_text("{}", encoding="utf-8")
    (root / module / "models" / "thing.py").write_text(
        MODEL.format(base=base, field=field), encoding="utf-8"
    )
    monkeypatch.setattr(gate, "scan_roots", lambda: [root])
    monkeypatch.setattr(gate, "module_names", lambda: {module: str(root)})
    monkeypatch.setattr(gate, "load_allowlist", lambda: allowed or {})
    return root


class TestWhatCounts:
    @pytest.mark.parametrize(
        "field",
        [
            "api_key = fields.Char()",
            "client_secret = fields.Char()",
            'ups_access_token = fields.Char(groups="base.group_system")',
            "pac_password = fields.Text()",
            "refresh_token = fields.Char(copy=False)",
        ],
    )
    def test_a_stored_secret_is_an_offence(self, tmp_path, monkeypatch, field):
        _write(tmp_path, monkeypatch, field)
        assert [f.field for f in gate.offenders()] == [field.split(" =")[0]]

    def test_a_listed_field_is_not(self, tmp_path, monkeypatch):
        _write(
            tmp_path,
            monkeypatch,
            "api_key = fields.Char()",
            allowed={"carrier.api_key": "why"},
        )
        assert gate.offenders() == []


class TestTheFourExclusions:
    """Each is in ADR-0081's decision, so each is asserted rather than assumed.

    A gate that fired on any of these would be argued down rather than obeyed.
    """

    def test_a_wizard_field_is_typed_used_and_gone(self, tmp_path, monkeypatch):
        _write(
            tmp_path,
            monkeypatch,
            "api_key = fields.Char()",
            base="TransientModel",
        )
        assert gate.offenders() == []

    @pytest.mark.parametrize(
        "name", ["invite_token", "document_token", "share_token", "portal_token"]
    )
    def test_a_token_we_mint_belongs_on_the_record_it_shares(
        self, tmp_path, monkeypatch, name
    ):
        _write(tmp_path, monkeypatch, f"{name} = fields.Char()")
        assert gate.offenders() == [], (
            "a share token travels in a URL; a vault would defeat its only purpose"
        )

    def test_a_compute_inverse_door_is_not_a_store(self, tmp_path, monkeypatch):
        _write(
            tmp_path,
            monkeypatch,
            'password = fields.Char(compute="_compute_password", '
            'inverse="_inverse_password")',
        )
        assert gate.offenders() == [], (
            "res.users.password and certificate.pkcs12_password are both this: "
            "the plain field writes through to a hash or an encrypted blob"
        )

    def test_a_stored_compute_is_still_a_store(self, tmp_path, monkeypatch):
        _write(
            tmp_path,
            monkeypatch,
            'password = fields.Char(compute="_compute_password", store=True)',
        )
        assert [f.field for f in gate.offenders()] == ["password"]

    @pytest.mark.parametrize(
        "name", ["token_hash", "token_masked", "credential_fingerprint"]
    )
    def test_something_derived_from_a_secret_is_not_the_secret(
        self, tmp_path, monkeypatch, name
    ):
        _write(tmp_path, monkeypatch, f"{name} = fields.Char()")
        assert gate.offenders() == []

    def test_a_field_written_from_a_hash_is_not_a_credential(
        self, tmp_path, monkeypatch
    ):
        """The name says plaintext and the code says otherwise.

        `website`'s `visibility_password` reads exactly like a stored password
        and holds `crypt_context.hash(...)`. `DERIVED` cannot see it: that rule
        goes by the suffix, and this one has none. Vaulting a hash would wrap a
        deliberately one-way value in something reversible.
        """
        _write(
            tmp_path,
            monkeypatch,
            "visibility_password = fields.Char()\n"
            "\n"
            "    def _inverse_display(self):\n"
            "        for r in self:\n"
            "            r.visibility_password = crypt_context.hash(r.display)",
        )
        assert gate.offenders() == []

    def test_a_password_merely_mentioned_near_a_hash_is_still_a_credential(
        self, tmp_path, monkeypatch
    ):
        """The rule keys on the assignment, not on the file containing `hash`."""
        _write(
            tmp_path,
            monkeypatch,
            "ldap_password = fields.Char()\n"
            "\n"
            "    def _check(self):\n"
            "        for r in self:\n"
            "            r.other_field = crypt_context.hash(r.display)",
        )
        assert [f.field for f in gate.offenders()] == ["ldap_password"]

    def test_a_key_we_publish_is_not_a_secret(self, tmp_path, monkeypatch):
        """Served to anonymous visitors by design, so there is nothing to protect.

        Vaulting it would also put a rate-limited decrypt behind an
        unauthenticated route, which is a way to take a site down.
        """
        _write(
            tmp_path,
            monkeypatch,
            "google_maps_api_key = fields.Char()",
            module="website",
        )
        assert gate.offenders() == []

    def test_its_near_namesake_used_server_side_is_still_a_secret(
        self, tmp_path, monkeypatch
    ):
        """The judgement is per field and does not follow the name."""
        _write(
            tmp_path,
            monkeypatch,
            "google_places_api_key = fields.Char()",
            module="website_sale_autocomplete",
        )
        assert [f.field for f in gate.offenders()] == ["google_places_api_key"]

    def test_the_vault_itself_is_exempt_by_construction(self, tmp_path, monkeypatch):
        _write(
            tmp_path, monkeypatch, "api_key = fields.Char()", module=gate.VAULT_MODULE
        )
        assert gate.offenders() == []


class TestWhatIsOutOfScope:
    @pytest.mark.parametrize(
        "field",
        [
            "token_type = fields.Char()",
            "api_key_header = fields.Char()",
            "credential_id = fields.Many2one('credential.credential')",
            "password_expiry = fields.Char()",
            "has_api_key = fields.Char()",
        ],
    )
    def test_a_name_about_a_secret_is_not_one(self, tmp_path, monkeypatch, field):
        _write(tmp_path, monkeypatch, field)
        assert gate.offenders() == []

    def test_a_non_char_field_is_out_of_scope(self, tmp_path, monkeypatch):
        _write(tmp_path, monkeypatch, "api_key = fields.Binary()")
        assert gate.offenders() == []

    def test_tests_and_migrations_are_skipped(self, tmp_path, monkeypatch):
        root = tmp_path / "addons"
        for part in ("tests", "migrations"):
            (root / "carrier" / part).mkdir(parents=True)
            (root / "carrier" / part / "thing.py").write_text(
                MODEL.format(base="Model", field="api_key = fields.Char()"),
                encoding="utf-8",
            )
        monkeypatch.setattr(gate, "scan_roots", lambda: [root])
        monkeypatch.setattr(gate, "load_allowlist", dict)
        assert gate.offenders() == []


class TestRefusals:
    def test_an_empty_tree_refuses_rather_than_passing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gate, "scan_roots", lambda: [tmp_path / "nowhere"])
        monkeypatch.setattr(gate, "load_allowlist", dict)
        monkeypatch.setattr(sys, "argv", ["credential_storage.py", "--check"])
        assert gate.main() == 1

    def test_prune_outside_a_workspace_refuses(self, monkeypatch):
        monkeypatch.setattr(gate, "in_full_workspace", lambda root: False)
        monkeypatch.setattr(sys, "argv", ["credential_storage.py", "--prune"])
        assert gate.main() == 1

    def test_there_is_no_update_flag(self):
        source = Path(gate.__file__).read_text(encoding="utf-8")
        assert 'add_argument("--update"' not in source, (
            "a flag that rewrote the allowlist to whatever the tree holds would "
            "let the next credential in silently"
        )


class TestRealTree:
    def test_the_allowlist_covers_the_tree(self):
        assert gate.offenders() == [], (
            "a stored third-party credential is unlisted; move it into "
            "credential.credential or add it to the allowlist with a reason"
        )

    def test_every_entry_carries_a_reason(self):
        blank = [key for key, why in gate.load_allowlist().items() if not why.strip()]
        assert not blank, f"allowlist entries with no reason: {blank}"

    def test_no_entry_is_dead(self):
        if not gate.in_full_workspace(gate.ROOT):
            pytest.skip("repo-alone checkout: the sibling roots are not present")
        present = {finding.key for finding in gate.findings()}
        dead = sorted(set(gate.load_allowlist()) - present)
        assert not dead, f"entries naming nothing in the tree: {dead}. Run --prune."


@pytest.mark.parametrize("flag", ["--check", "--count", "--list"])
def test_the_cli_exits_zero_on_the_real_tree(monkeypatch, flag):
    monkeypatch.setattr(sys, "argv", ["credential_storage.py", flag])
    assert gate.main() == 0


class TestACursorIsNotACredential:
    """The fifth exclusion, found before any module was migrated on it.

    `google_calendar_sync_token` is labelled "Next Sync Token" in its own field
    definition, is read from `nextSyncToken` in the response and is sent back as
    `params['syncToken']`. It authorises nothing and changes on every sync.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "google_calendar_sync_token",
            "microsoft_calendar_sync_token",
            "page_token",
            "next_token",
            "delta_cursor",
        ],
    )
    def test_a_feed_cursor_is_state_not_a_secret(self, tmp_path, monkeypatch, name):
        _write(tmp_path, monkeypatch, f"{name} = fields.Char()")
        assert gate.offenders() == [], (
            "vaulting a cursor would churn the store and its access log on every "
            "sync, for a value that authorises nothing"
        )

    def test_a_secret_whose_name_merely_ends_in_token_still_counts(
        self, tmp_path, monkeypatch
    ):
        _write(tmp_path, monkeypatch, "ups_access_token = fields.Char()")
        assert [f.field for f in gate.offenders()] == ["ups_access_token"]


class TestTheFourAmbiguousNames:
    """`access_token`, `token`, `sms_token`, `push_token` carry both kinds.

    No pattern separates them and neither does a generator: `portal.access_token`
    is minted in a method, not a field default. What separates them is whom the
    token authorises, so the judgement is recorded per field.
    """

    def test_a_share_token_named_in_the_set_is_excluded(self, tmp_path, monkeypatch):
        _write(tmp_path, monkeypatch, "access_token = fields.Char()", module="portal")
        assert gate.offenders() == []

    def test_the_same_name_elsewhere_is_a_credential(self, tmp_path, monkeypatch):
        _write(tmp_path, monkeypatch, "access_token = fields.Char()", module="carrier")
        assert [f.key for f in gate.offenders()] == ["carrier.access_token"]

    def test_the_five_unambiguous_names_need_no_entry(self, tmp_path, monkeypatch):
        for name in (
            "share_token",
            "invite_token",
            "document_token",
            "portal_token",
            "signup_token",
        ):
            _write(
                tmp_path / name, monkeypatch, f"{name} = fields.Char()", module="thing"
            )
            assert gate.offenders() == [], name

    def test_every_named_share_field_still_exists(self):
        if not gate.in_full_workspace(gate.ROOT):
            pytest.skip("repo-alone checkout: the sibling roots are not present")
        # a SHARE_FIELDS entry naming nothing is a rule kept for a field that is
        # gone, which is how an exclusion outlives its reason
        for key in gate.SHARE_FIELDS:
            module = key.split(".", 1)[0]
            assert module in gate.module_names(), (
                f"{key} names a module the tree does not have"
            )


class TestKeysThatAreNotSecrets:
    """`_key` joined SECRET, so the counterparts have to hold."""

    @pytest.mark.parametrize(
        "name",
        [
            "stripe_publishable_key",
            "mercado_pago_public_key",
            "turnstile_site_key",
            "buckaroo_website_key",
            "adyen_client_key",
        ],
    )
    def test_a_key_published_to_the_browser_is_not_a_secret(
        self, tmp_path, monkeypatch, name
    ):
        _write(tmp_path, monkeypatch, f"{name} = fields.Char()")
        assert gate.offenders() == []

    @pytest.mark.parametrize(
        "name", ["cache_key", "bucket_key", "grouping_key", "identity_key"]
    )
    def test_a_lookup_key_is_not_a_credential(self, tmp_path, monkeypatch, name):
        """`ir.job.identity_key` is the dedup key that stops one job being
        enqueued twice. It authorises nothing."""
        _write(tmp_path, monkeypatch, f"{name} = fields.Char()")
        assert gate.offenders() == []

    @pytest.mark.parametrize(
        "name",
        [
            "adyen_hmac_key",
            "paymob_hmac_key",
            "authorize_signature_key",
            "authorize_transaction_key",
            "openai_key",
        ],
    )
    def test_a_signing_key_is_a_secret_however_it_is_spelled(
        self, tmp_path, monkeypatch, name
    ):
        """The gap `_key` closed: `api_?key` matched none of these, and every
        one is a stored secret the gate reported nothing about."""
        _write(tmp_path, monkeypatch, f"{name} = fields.Char()")
        assert [f.field for f in gate.offenders()] == [name]
