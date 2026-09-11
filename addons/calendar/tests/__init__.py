from . import test_access_rights
from . import test_attendees
from . import test_calendar
from . import test_calendar_activity
from . import test_calendar_controller
from . import test_calendar_reservation
from . import test_calendar_recurrence_legacy
from . import test_calendar_tour
from . import test_event_recurrence
from . import test_event_notifications
from . import test_mail_activity_mixin
from . import test_privacy_delegation
from . import test_res_partner
from . import test_recurrence_rule
from . import test_res_users
from . import test_regressions
from . import test_calendar_stop_create

from .booking import test_appointment as test_booking_appointment
from .booking import test_appointment_invite as test_booking_appointment_invite
from .booking import (
    test_appointment_invite_security as test_booking_appointment_invite_security,
)
from .booking import (
    test_appointment_notifications as test_booking_appointment_notifications,
)
from .booking import test_appointment_resource as test_booking_appointment_resource
from .booking import (
    test_appointment_slot_security as test_booking_appointment_slot_security,
)
from .booking import (
    test_appointment_type_security as test_booking_appointment_type_security,
)
from .booking import test_appointment_ui as test_booking_appointment_ui
from .booking import test_calendar_event as test_booking_calendar_event
from .booking import test_controller_security as test_booking_controller_security
from .booking import test_event_notification as test_booking_event_notification
from .booking import test_manage_leaves as test_booking_manage_leaves
from .booking import test_performance as test_booking_performance
from .booking import test_res_partner as test_booking_res_partner
from .booking import (
    test_slot_end_hour_on_create as test_booking_slot_end_hour_on_create,
)
from .booking import test_survey_questions as test_booking_survey_questions

from . import test_booking_consolidation

from . import test_booking_migration
