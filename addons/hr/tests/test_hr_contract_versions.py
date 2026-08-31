from datetime import date

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHrContractVersions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create(
            {
                "name": "Test Company",
                "country_id": cls.env.ref("base.us").id,
            }
        )
        cls.env.user.company_id = cls.company
        cls.employee = cls.env["hr.employee"].create(
            {"name": "John Doe", "date_version": "2025-01-01"}
        )

    def create_version(self, date_version):
        return self.employee.create_version(
            {
                "date_version": date_version,
            }
        )

    def create_versions(self, *dates):
        res = self.env["hr.version"]
        for date_version in dates:
            res |= self.create_version(date_version)
        return res

    def assert_get_contract_versions(
        self, date_start, date_end, versions_per_contract_expected
    ):
        versions_per_contract = self.employee._get_contract_versions(
            date_start, date_end
        )[self.employee.id]
        self.assertEqual(
            len(versions_per_contract),
            len(versions_per_contract_expected),
            "%s contract should be found" % len(versions_per_contract_expected),
        )
        for vpc, vpc_e in zip(
            versions_per_contract.values(), versions_per_contract_expected, strict=False
        ):
            self.assertEqual(
                vpc,
                vpc_e,
                "invalid number of versions (%s instead of %s) for this contract : contract_date_start : %s"
                % (len(vpc), len(vpc_e), vpc_e[0].contract_date_start),
            )

    def assert_get_contracts(self, date_start, date_end, contracts_expected):
        contracts = self.employee._get_contracts(date_start, date_end)[self.employee.id]
        if not contracts_expected:
            expected_ids = []
        elif isinstance(contracts_expected, (list, tuple)):
            expected_ids = [rec.id for rec in contracts_expected]
        else:
            expected_ids = contracts_expected.ids
        self.assertEqual(
            len(contracts),
            len(expected_ids),
            "wrong number of contracts (%s instead of %s)"
            % (len(contracts), len(expected_ids)),
        )
        self.assertEqual(set(contracts.ids), set(expected_ids), "invalid contracts")

    def test_0contract_1version(self):
        for date_version in ["2025-01-01", "2025-06-01", "2025-12-31"]:
            self.employee.date_version = date_version
            for date_start in (None, date(2025, 3, 1)):
                for date_end in (None, date(2025, 6, 15)):
                    self.assert_get_contract_versions(date_start, date_end, [])
                    self.assert_get_contracts(date_start, date_end, [])

    """ Timeline for this test
        V  : versions
        C  : first version of the contract
        =  : contract

        1/
                     04/01               7/31
        2025|C---------=====================----------|
           01/01               06/01                12/31

        2/
                     04/01               7/31
        2025|----------==========C==========----------|
           01/01               06/01                12/31

        3/
                     04/01               7/31
        2025|----------=====================---------C|
           01/01               06/01                12/31
    """

    def test_1contract_1version(self):
        unique_version = self.employee.version_id
        unique_version.contract_date_start = date(2025, 4, 1)
        unique_version.contract_date_end = date(2025, 7, 31)
        for date_version in ["2025-01-01", "2025-06-01", "2025-12-31"]:
            unique_version.date_version = date_version
            for date_start in (None, date(2025, 3, 1), date(2025, 4, 1)):
                for date_end in (
                    None,
                    date(2025, 4, 1),
                    date(2025, 6, 15),
                    date(2025, 7, 31),
                ):
                    self.assert_get_contract_versions(
                        date_start, date_end, [unique_version]
                    )
                    self.assert_get_contracts(date_start, date_end, unique_version)

    """ Timeline for this setup
        V  : versions
        C  : first version of the contract
        =  : contract

                     04/01=========================07/31
        2025|C---------V---------------V------V--------VV---------|
           01/01     04/01           06/01  07/01  07/31;08/01
    """

    def setup_1contract_5version(self):
        contract_versions = self.employee.version_id | self.create_versions(
            date(2025, 4, 1), date(2025, 6, 1), date(2025, 7, 1), date(2025, 7, 31)
        )
        contract_versions.contract_date_start = date(2025, 4, 1)
        contract_versions.contract_date_end = date(2025, 7, 31)
        versions_not_in_contract = self.create_version(date(2025, 8, 1))
        return contract_versions, versions_not_in_contract

    def test_1contract_5version(self):
        expected_contract_versions, _ = self.setup_1contract_5version()
        self.assert_get_contract_versions(None, None, [expected_contract_versions])
        self.assert_get_contracts(None, None, expected_contract_versions[-1])

    def test_1contract_5version_w_date_start(self):
        expected_contract_versions, _ = self.setup_1contract_5version()
        self.assert_get_contract_versions(
            date(2025, 3, 1), None, [expected_contract_versions]
        )
        self.assert_get_contracts(
            date(2025, 3, 1), None, expected_contract_versions[-1]
        )

    def test_1contract_5version_w_date_start_date_end(self):
        expected_contract_versions, _ = self.setup_1contract_5version()
        self.assert_get_contract_versions(
            date(2025, 5, 15), date(2025, 6, 15), [expected_contract_versions]
        )
        self.assert_get_contracts(
            date(2025, 4, 15), date(2025, 6, 15), expected_contract_versions[2]
        )
        self.assert_get_contracts(
            date(2025, 6, 15), date(2025, 7, 15), expected_contract_versions[3]
        )

    def test_1contract_5version_w_date_end(self):
        expected_contract_versions, _ = self.setup_1contract_5version()
        self.assert_get_contract_versions(
            None, date(2025, 8, 31), [expected_contract_versions]
        )
        self.assert_get_contracts(
            None, date(2025, 8, 31), expected_contract_versions[-1]
        )
        self.assert_get_contracts(
            None, date(2025, 7, 31), expected_contract_versions[-1]
        )
        self.assert_get_contracts(
            None, date(2025, 7, 30), expected_contract_versions[-2]
        )

    """ Timeline for this setup
        V  : versions
        C  : first version of the contract
        =  : contract

                      4/01              5/15 6/15              7/31
        2025|C---------====================-C-====================----------|
           01/01                          06/01
    """

    def setup_2contract_1version_each(self):
        contract_1_version = self.employee.version_id
        contract_1_version.contract_date_start = date(2025, 4, 1)
        contract_1_version.contract_date_end = date(2025, 5, 15)

        contract_2_version = self.create_version(date(2025, 6, 1))
        contract_2_version.contract_date_start = date(2025, 6, 15)
        contract_2_version.contract_date_end = date(2025, 7, 31)

        return contract_1_version, contract_2_version

    def test_2contract_1version_each(self):
        contract_1_version, contract_2_version = self.setup_2contract_1version_each()
        self.assert_get_contract_versions(
            None, None, [contract_1_version, contract_2_version]
        )
        self.assert_get_contracts(None, None, contract_1_version | contract_2_version)
        self.assert_get_contracts(None, None, contract_1_version | contract_2_version)

    def test_2contract_1version_each_w_date_start(self):
        contract_1_version, contract_2_version = self.setup_2contract_1version_each()
        self.assert_get_contract_versions(
            date(2025, 3, 1), None, [contract_1_version, contract_2_version]
        )
        self.assert_get_contract_versions(date(2025, 6, 15), None, [contract_2_version])
        self.assert_get_contracts(
            date(2025, 3, 1), None, contract_1_version | contract_2_version
        )

    def test_2contract_1version_each_w_date_start_date_end(self):
        contract_1_version, contract_2_version = self.setup_2contract_1version_each()
        self.assert_get_contract_versions(date(2025, 5, 16), date(2025, 6, 14), [])
        self.assert_get_contract_versions(
            date(2025, 5, 15),
            date(2025, 6, 15),
            [contract_1_version, contract_2_version],
        )
        self.assert_get_contracts(
            date(2025, 5, 15), date(2025, 6, 14), contract_1_version
        )
        self.assert_get_contracts(
            date(2025, 5, 16), date(2025, 6, 15), contract_2_version
        )
        self.assert_get_contracts(
            date(2025, 5, 15),
            date(2025, 6, 15),
            [contract_1_version, contract_2_version],
        )

    def test_2contract_1version_each_w_date_end(self):
        contract_1_version, contract_2_version = self.setup_2contract_1version_each()
        self.assert_get_contract_versions(
            None, date(2025, 8, 31), [contract_1_version, contract_2_version]
        )
        self.assert_get_contract_versions(
            None, date(2025, 6, 15), [contract_1_version, contract_2_version]
        )
        self.assert_get_contract_versions(None, date(2025, 6, 14), [contract_1_version])
        self.assert_get_contracts(
            None, date(2025, 8, 31), contract_1_version | contract_2_version
        )

    """ Timeline for this setup
        V  : versions
        C  : first version of the contract
        =  : contract

                       4/01============5/15               6/15============7/31
        2025|C---------V------------------VV------C-------V------------------VV---------|
            1/1       4/1              5/15;5/16 6/1      6/15            7/31;8/1
    """

    def setup_2contract_3version_each(self):
        contract_1_versions = self.employee.version_id | self.create_versions(
            date(2025, 4, 1),
            date(2025, 5, 15),
        )
        contract_1_versions.contract_date_start = date(2025, 4, 1)
        contract_1_versions.contract_date_end = date(2025, 5, 15)

        versions_not_in_contract = self.create_version(date(2025, 5, 16))

        contract_2_versions = self.create_versions(
            date(2025, 6, 1),
            date(2025, 6, 15),
            date(2025, 7, 31),
        )
        contract_2_versions.contract_date_start = date(2025, 6, 15)
        contract_2_versions.contract_date_end = date(2025, 7, 31)

        versions_not_in_contract |= self.create_version(date(2025, 8, 1))

        return contract_1_versions, contract_2_versions, versions_not_in_contract

    def test_2contract_3version_each(self):
        contract_1_version, contract_2_version, _ = self.setup_2contract_3version_each()
        self.assert_get_contract_versions(
            None, None, [contract_1_version, contract_2_version]
        )
        self.assert_get_contracts(
            None, None, contract_1_version[-1] | contract_2_version[-1]
        )

    def test_2contract_3version_each_w_date_start(self):
        contract_1_version, contract_2_version, _ = self.setup_2contract_3version_each()
        self.assert_get_contract_versions(
            date(2025, 3, 1), None, [contract_1_version, contract_2_version]
        )
        self.assert_get_contracts(
            date(2025, 3, 1), None, contract_1_version[-1] | contract_2_version[-1]
        )

    def test_2contract_3version_each_w_date_start_date_end(self):
        contract_1_version, contract_2_version, _ = self.setup_2contract_3version_each()
        self.assert_get_contract_versions(date(2025, 5, 16), date(2025, 6, 14), [])
        self.assert_get_contracts(
            date(2025, 4, 15),
            date(2025, 6, 15),
            [contract_1_version[-1], contract_2_version[1]],
        )
        self.assert_get_contracts(
            date(2025, 6, 15), date(2025, 7, 31), contract_2_version[-1]
        )

    def test_2contract_3version_each_w_date_end(self):
        contract_1_version, contract_2_version, _ = self.setup_2contract_3version_each()
        self.assert_get_contract_versions(
            None, date(2025, 8, 31), [contract_1_version, contract_2_version]
        )
        self.assert_get_contracts(
            None, date(2025, 8, 31), contract_1_version[-1] | contract_2_version[-1]
        )
        self.assert_get_contracts(
            None, date(2025, 7, 31), contract_1_version[-1] | contract_2_version[-1]
        )
        self.assert_get_contracts(
            None, date(2025, 7, 30), contract_1_version[-1] | contract_2_version[-2]
        )
