import datetime

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.spreadsheet.utils.formatting import (
    date_to_spreadsheet_date_number,
    datetime_to_spreadsheet_date_number,
)
from odoo.addons.spreadsheet.utils.helpers import spreadsheet_safe_batch
from odoo.addons.spreadsheet.utils.json import extend_serialized_json


class TestSpreadsheetUtils(TransactionCase):
    def test_extend_serialized_json(self):
        self.assertEqual(extend_serialized_json("{}", []), "{}")
        self.assertEqual(extend_serialized_json("{}", [("key", "{}")]), '{"key":{}}')
        self.assertEqual(extend_serialized_json("{}", [("key", "[]")]), '{"key":[]}')
        self.assertEqual(
            extend_serialized_json("{}", [("key", '"value"')]), '{"key":"value"}'
        )
        self.assertEqual(
            extend_serialized_json('{"a": 1}', [("key", '"value"')]),
            '{"a": 1,"key":"value"}',
        )
        self.assertEqual(
            extend_serialized_json('{"a": 1}', [("key", '{"b": 2}')]),
            '{"a": 1,"key":{"b": 2}}',
        )
        self.assertEqual(
            extend_serialized_json('{"a": {}}', [("key", '{"b": 2}')]),
            '{"a": {},"key":{"b": 2}}',
        )
        self.assertEqual(
            extend_serialized_json('{"a": 1}', [("key", "[]")]), '{"a": 1,"key":[]}'
        )
        self.assertEqual(
            extend_serialized_json('{"a": []}', [("key", "[]")]), '{"a": [],"key":[]}'
        )
        self.assertEqual(
            extend_serialized_json("{}", [("key1", "1"), ("key2", "2")]),
            '{"key1":1,"key2":2}',
        )

    def test_date_to_spreadsheet_date_number(self):
        d = datetime.date(1899, 12, 30)
        self.assertEqual(date_to_spreadsheet_date_number(d), 0)

        d = datetime.date(2023, 10, 1)
        self.assertEqual(date_to_spreadsheet_date_number(d), 45200)

    def test_datetime_to_spreadsheet_date_number(self):
        test_tz_offset = 8 / 24  # Etc/GMT-8 is UTC+8
        dt = datetime.datetime(1899, 12, 30, 0, 0, 0)
        self.assertEqual(datetime_to_spreadsheet_date_number(dt, "UTC"), 0)

        dt = datetime.datetime(1899, 12, 30, 0, 0, 0)
        self.assertEqual(
            datetime_to_spreadsheet_date_number(dt, "Etc/GMT-8"), test_tz_offset
        )

        dt = datetime.datetime(2023, 10, 1, 12, 0, 0)
        self.assertEqual(datetime_to_spreadsheet_date_number(dt, "UTC"), 45200.5)

        dt = datetime.datetime(2023, 10, 1, 12, 0, 0)
        self.assertEqual(
            datetime_to_spreadsheet_date_number(dt, "Etc/GMT-8"),
            45200.5 + test_tz_offset,
        )


class TestSpreadsheetSafeBatch(TransactionCase):
    """The client sends one RPC per batch and no longer retries request by
    request, so isolating a failing request is now the server's job.
    """

    def test_a_failing_request_no_longer_sinks_its_batch(self):
        calls = []

        @spreadsheet_safe_batch
        def fetch(self, requests):
            calls.append(list(requests))
            results = []
            for request in requests:
                if request == "bad":
                    raise UserError("no such thing")
                results.append("value:%s" % request)
            return results

        self.assertEqual(
            fetch(self.env["res.currency.rate"], ["a", "bad", "b"]),
            ["value:a", {"__error__": "no such thing"}, "value:b"],
        )
        # the batch is attempted whole first, and only then request by request
        self.assertEqual(calls, [["a", "bad", "b"], ["a"], ["bad"], ["b"]])

    def test_a_clean_batch_is_executed_once(self):
        calls = []

        @spreadsheet_safe_batch
        def fetch(self, requests):
            calls.append(list(requests))
            return ["value:%s" % request for request in requests]

        self.assertEqual(
            fetch(self.env["res.currency.rate"], ["a", "b"]),
            ["value:a", "value:b"],
        )
        self.assertEqual(calls, [["a", "b"]], "no per-request retry on success")

    def test_a_programming_error_still_propagates(self):
        @spreadsheet_safe_batch
        def fetch(self, requests):
            raise KeyError("from")

        with self.assertRaises(KeyError):
            fetch(self.env["res.currency.rate"], ["a"])

    def test_every_batched_endpoint_is_decorated(self):
        """The client reports a generic error for a whole failed batch now, so
        an endpoint that loses the decorator silently stops isolating failures.
        """
        endpoints = [
            ("res.currency.rate", "get_rates_for_spreadsheet"),
            ("mixin.spreadsheet", "get_display_names_for_spreadsheet"),
        ]
        for model_name, method_name in endpoints:
            with self.subTest(model=model_name, method=method_name):
                method = getattr(self.env[model_name], method_name)
                self.assertTrue(
                    hasattr(method, "__wrapped__"),
                    "%s.%s is batched by the client but is not wrapped in "
                    "spreadsheet_safe_batch" % (model_name, method_name),
                )
