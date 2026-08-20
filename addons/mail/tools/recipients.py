from typing import Literal, NamedTuple, TypedDict


class RecipientData(TypedDict):
    active: bool
    email_normalized: str | Literal[False] | None
    groups: frozenset[int]
    id: int | Literal[False]
    is_follower: bool
    lang: str | Literal[False] | None
    name: str | Literal[False] | None
    notif: str
    share: bool
    type: Literal["user", "portal", "customer"]
    uid: int | Literal[False] | None
    ushare: bool


class RecipientRow(NamedTuple):
    partner_id: int
    active: bool
    email_normalized: str | None
    lang: str | None
    name: str | None
    partner_share: bool
    uid: int | None
    user_share: bool
    notif: str
    group_ids: list[int] | None
    res_id: int
    is_follower: bool


def build_recipient_data(
    *,
    partner_id: int | Literal[False] = False,
    active: bool = True,
    email_normalized: str | Literal[False] | None = False,
    groups: frozenset[int] = frozenset(),
    is_follower: bool = False,
    lang: str | Literal[False] | None = False,
    name: str | Literal[False] | None = False,
    notif: str = "email",
    partner_share: bool = True,
    uid: int | Literal[False] | None = False,
    user_share: bool = False,
) -> RecipientData:
    return {
        "active": active,
        "email_normalized": email_normalized,
        "groups": groups,
        "id": partner_id,
        "is_follower": is_follower,
        "lang": lang,
        "name": name,
        "notif": notif,
        "share": partner_share,
        "type": "portal" if user_share else "customer" if partner_share else "user",
        "uid": uid,
        "ushare": user_share,
    }
