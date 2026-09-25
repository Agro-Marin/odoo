"""The environment a login finalizes under belongs to the user signing in."""

from types import SimpleNamespace

from odoo.http._session_store import MemorySessionStore
from odoo.http.constants import prepare_default_session
from odoo.http.session import Session


class LoginEnv:
    """The request's environment, and every one derived from it."""

    def __init__(self, uid, context, seen):
        self.uid = uid
        self.context = context
        self.cr = None
        self.registry = SimpleNamespace(db_name="db")
        self._seen = seen

    def __call__(self, user=None, context=None):
        return LoginEnv(
            self.uid if user is None else user,
            self.context if context is None else context,
            self._seen,
        )

    def __getitem__(self, model):
        assert model == "res.users"
        self._seen.append((self.uid, dict(self.context)))
        return SimpleNamespace(
            context_get=lambda: {"lang": "es_MX"},
            browse=lambda uid: SimpleNamespace(
                _get_session_token=lambda sid: f"{uid}:{sid}"
            ),
        )

    @property
    def user(self):
        return SimpleNamespace(_get_session_token=lambda sid: f"{self.uid}:{sid}")


def finalize(context):
    store = MemorySessionStore(Session)
    session = store.new()
    session.update(prepare_default_session(), pre_login="user", pre_uid=7)
    seen: list[tuple[int, dict]] = []
    session.finalize_login(LoginEnv(3, context, seen))
    return session, seen


def test_a_login_drops_the_companies_chosen_for_the_public_user():
    session, seen = finalize(
        {"allowed_company_ids": [1], "website_id": 1, "lang": "en_US"}
    )
    assert session.uid == 7
    assert seen, "the user's context is read under the finalized environment"
    for uid, context in seen:
        assert uid == 7
        assert "allowed_company_ids" not in context
        assert context["website_id"] == 1, "only the companies are dropped"


def test_a_login_without_companies_in_context_keeps_the_context():
    _session, seen = finalize({"website_id": 1})
    assert seen == [(7, {"website_id": 1})]
