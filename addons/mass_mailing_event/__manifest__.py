# -*- coding: utf-8 -*-
{
    'name': 'Mass mailing on attendees',
    'category': 'Marketing/Email Marketing',
    'version': '1.0',
    'description':
        """
Mass mail event attendees
=========================

Bridge module adding UX requirements to ease mass mailing of event attendees.
        """,
    'depends': ['event', 'mass_mailing'],
    'data': [
        'views/event_views.xml'
    ],
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
