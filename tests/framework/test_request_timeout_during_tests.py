import pytest

import odoo.init  # noqa: F401  imported for the bootstrap side effect
from odoo.tests import transaction_case


@pytest.mark.parametrize(
    ("timeout", "raised"),
    [
        (None, None),
        (0, 0),
        (3, 10),
        (30, 30),
        ((3, 30), (10, 30)),
        ((3, None), (10, None)),
        ((12, 5), (12, 10)),
    ],
)
def test_every_part_of_a_timeout_gets_ten_seconds(timeout, raised):
    assert transaction_case._raise_test_timeout(timeout) == raised


def test_a_connect_read_pair_to_an_external_host_is_blocked_not_a_type_error():
    class Request:
        url = "https://api.telegram.org/bot/answerCallbackQuery"
        method = "POST"

    with pytest.raises(transaction_case.BlockedRequest):
        transaction_case.TransactionCase._request_handler(
            None, Request(), timeout=(3, 30)
        )
