from datetime import datetime

import pytest

from odoo import fields


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2000", datetime(2000, 1, 1)),
        ("2000-03", datetime(2000, 3, 1)),
        ("2000-03-04", datetime(2000, 3, 4)),
        ("2000-03-04 10", datetime(2000, 3, 4, 10)),
        ("2000-03-04 10:20", datetime(2000, 3, 4, 10, 20)),
        ("2000-03-04 10:20:30", datetime(2000, 3, 4, 10, 20, 30)),
        ("2000-03-04T10:20:30", datetime(2000, 3, 4, 10, 20, 30)),
    ],
)
def test_to_datetime_reads_every_leading_part_of_the_server_format(value, expected):
    assert fields.Datetime.to_datetime(value) == expected


@pytest.mark.parametrize("value", ["2000-3", "2000-03-4", "03/04/2000"])
def test_to_datetime_still_refuses_a_value_the_format_cannot_describe(value):
    with pytest.raises(ValueError):
        fields.Datetime.to_datetime(value)
