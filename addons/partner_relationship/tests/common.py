from odoo.addons.base.tests.common import BaseCommon


class PartnerRelationCommon(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.relations = cls.env["res.partner.relation"]
        cls.type_parent = cls.quick_ref("partner_relationship.relation_type_parent")
        cls.type_sibling = cls.quick_ref("partner_relationship.relation_type_sibling")
        cls.type_spouse = cls.quick_ref("partner_relationship.relation_type_spouse")
        cls.type_compadre = cls.quick_ref("partner_relationship.relation_type_compadre")
        cls.type_crop = cls.quick_ref("partner_relationship.relation_type_croppartner")
        cls.type_guarantor = cls.quick_ref(
            "partner_relationship.relation_type_guarantor"
        )

        cls.juan = cls._create_person("Juan", "male")
        cls.maria = cls._create_person("Maria", "female")
        cls.pedro = cls._create_person("Pedro", "male")
        cls.lucia = cls._create_person("Lucia", "female")
        cls.stranger = cls._create_person("Stranger", "female")

    @classmethod
    def _create_person(cls, name, gender):
        return cls.env["res.partner"].create({"name": name, "gender": gender})

    @classmethod
    def _create_relation(cls, partner, relation_type, other_partner):
        return cls.env["res.partner.relation"].create(
            {
                "partner_id": partner.id,
                "type_id": relation_type.id,
                "other_partner_id": other_partner.id,
            }
        )
