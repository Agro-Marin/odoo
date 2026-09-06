from odoo.tools.module_data import adopt_xmlids, retire_empty_module

FROM_MODULE = "group_readonly"
MODULE = "event_sale"
ADOPTED = (
    "access_event_registration_sale_readonly",
    "access_event_event_sale_readonly",
    "access_event_event_ticket_sale_readonly",
    "access_event_type_sale_readonly",
)


def migrate(cr, version):
    if not version:
        return
    adopt_xmlids(cr, FROM_MODULE, MODULE, ADOPTED)
    retire_empty_module(cr, FROM_MODULE)
