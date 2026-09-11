from odoo.tests import TransactionCase


class TestVersionStructureType(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.country_id = cls.env.ref("base.us")
        StructureType = cls.env["hr.payroll.structure.type"]
        cls.us_type = StructureType.create(
            {"name": "US salaried", "country_id": cls.env.ref("base.us").id}
        )
        cls.ar_type = StructureType.create(
            {"name": "AR mensual", "country_id": cls.env.ref("base.ar").id}
        )
        cls.company_ar = cls.env["res.company"].create(
            {"name": "Argentina branch", "country_id": cls.env.ref("base.ar").id}
        )
        cls.env.user.company_ids |= cls.company_ar
        cls.versions = cls.env["hr.version"].with_context(
            allowed_company_ids=[cls.env.company.id, cls.company_ar.id]
        )
        cls.employee_ar = (
            cls.env["hr.employee"]
            .with_context(allowed_company_ids=[cls.env.company.id, cls.company_ar.id])
            .create({"name": "Lucía", "company_id": cls.company_ar.id})
        )

    def test_a_version_for_another_countrys_company_takes_that_countrys_structure(self):
        version = self.versions.create(
            {
                "employee_id": self.employee_ar.id,
                "company_id": self.company_ar.id,
                "date_version": "2031-01-01",
            }
        )

        self.assertEqual(version.structure_type_id, self.ar_type)

    def test_an_explicit_structure_type_is_kept(self):
        version = self.versions.create(
            {
                "employee_id": self.employee_ar.id,
                "company_id": self.company_ar.id,
                "date_version": "2031-01-01",
                "structure_type_id": self.us_type.id,
            }
        )

        self.assertEqual(version.structure_type_id, self.us_type)
