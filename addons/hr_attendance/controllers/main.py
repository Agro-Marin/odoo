from datetime import UTC

from requests.exceptions import RequestException

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain
from odoo.http import request
from odoo.libs.datetime import timezone
from odoo.service.common import exp_version
from odoo.tools import SQL, float_round, py_to_js_locale
from odoo.tools.image import image_data_uri


class HrAttendance(http.Controller):
    @staticmethod
    def _get_company(token):
        return (
            request.env["res.company"]
            .sudo()
            .search([("attendance_kiosk_key", "=", token)])
        )

    @staticmethod
    def _get_overtime_today(employee):
        today = (
            fields.Datetime.now()
            .replace(tzinfo=UTC)
            .astimezone(timezone(employee._get_tz()))
            .date()
        )
        groups = (
            employee.env["hr.attendance.overtime.line"]
            .sudo()
            ._read_group(
                domain=[("employee_id", "=", employee.id), ("date", "=", today)],
                aggregates=["duration:sum"],
            )
        )
        return groups[0][0] or 0

    @staticmethod
    def _get_employee_info_response(employee):
        response = {}
        if employee:
            response = {
                **employee._get_attendance_systray_data(),
                "employee_name": employee.name,
                "employee_avatar": employee.image_256
                and image_data_uri(employee.image_256),
                "total_overtime": float_round(
                    employee.total_overtime, precision_digits=2
                ),
                "kiosk_delay": employee.company_id.attendance_kiosk_delay * 1000,
                "attendance": {
                    "check_in": employee.last_attendance_id.check_in,
                    "check_out": employee.last_attendance_id.check_out,
                },
                "overtime_today": HrAttendance._get_overtime_today(employee),
                "use_pin": employee.company_id.attendance_kiosk_use_pin,
                "display_overtime": employee.company_id.hr_attendance_display_overtime,
                "device_tracking_enabled": employee.company_id.attendance_device_tracking,
            }
        return response

    @staticmethod
    def _get_geoip_response(
        mode, latitude=False, longitude=False, device_tracking_enabled=True
    ):
        response = {"mode": mode}

        if not device_tracking_enabled:
            return response
        # The IP's coordinates stand in for missing GPS ones, so they have to
        # be settled before the coordinates are turned into a place name.
        if latitude is False or latitude is None:
            latitude = request.geoip.location.latitude
        if longitude is False or longitude is None:
            longitude = request.geoip.location.longitude
        try:
            location = request.env["geocoder"]._get_localisation(latitude, longitude)
        except UserError, RequestException:
            location = _("Unknown")
        response.update(
            {
                "location": location,
                "latitude": latitude if latitude is not None else False,
                "longitude": longitude if longitude is not None else False,
                "ip_address": request.geoip.ip,
                "browser": request.httprequest.user_agent.browser,
            }
        )

        return response

    @http.route(
        "/hr_attendance/kiosk_mode_menu/<int:company_id>", auth="user", type="http"
    )
    def kiosk_menu_item_action(self, company_id):
        if request.env.user.has_group("hr_attendance.group_hr_attendance_user"):
            if self.has_password():
                request.session.logout(keep_db=True)
            return request.redirect(
                request.env["res.company"].browse(company_id).attendance_kiosk_url
            )
        else:
            return request.not_found()

    @http.route(
        "/hr_attendance/get_employees_without_badge", type="jsonrpc", auth="public"
    )
    def get_employees_without_badge(self, token, name=None, limit=20):
        company = self._get_company(token)
        if company:
            domain = Domain([("barcode", "=", False), ("company_id", "=", company.id)])
            if name:
                domain = Domain.AND([domain, [("name", "ilike", name)]])
            employee_list = request.env["hr.employee"].search_read(
                domain,
                ["id", "name"],
                limit=limit,
            )
            return {"status": "success", "employees": employee_list}
        return {}

    @http.route("/hr_attendance/set_badge", type="jsonrpc", auth="public")
    def set_badge(self, employee_id, badge, token):
        company = self._get_company(token)
        if not company:
            return {}
        employee = request.env["hr.employee"].sudo().browse(employee_id).exists()
        if not employee or employee.company_id != company:
            return {}
        if employee.barcode:
            return {
                "status": "error",
                "message": _("This employee already has a badge."),
            }
        try:
            request.env["hr.employee"].browse(employee.id).barcode = badge
        except AccessError:
            return {
                "status": "error",
                "message": _("You are not allowed to assign badges."),
            }
        return {"status": "success"}

    @http.route("/hr_attendance/create_employee", type="jsonrpc", auth="public")
    def create_employee(self, name, token):
        company = self._get_company(token)
        if company:
            request.env["hr.employee"].create(
                {
                    "name": name,
                    "company_id": company.id,
                }
            )
            return True
        return False

    @http.route("/hr_attendance/kiosk_keepalive", auth="user", type="jsonrpc")
    def kiosk_keepalive(self):
        request.session.mark_dirty()
        return {}

    @http.route(
        ["/hr_attendance/<token>"],
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def open_kiosk_mode(self, token, from_trial_mode=False):
        company = self._get_company(token)
        if not company:
            return request.not_found()
        else:
            department_list = [
                {"id": dep["id"], "name": dep["name"], "count": dep["total_employee"]}
                for dep in request.env["hr.department"]
                .with_context(allowed_company_ids=[company.id])
                .sudo()
                .search_read(
                    domain=[("company_id", "=", company.id)],
                    fields=["id", "name", "total_employee"],
                )
            ]
            has_password = self.has_password()
            if not from_trial_mode and has_password:
                request.session.logout(keep_db=True)
            if from_trial_mode or (not has_password and not request.env.user.is_public):
                kiosk_mode = "settings"
            else:
                kiosk_mode = company.attendance_kiosk_mode
            version_info = exp_version()
            return request.render(
                "hr_attendance.public_kiosk_mode",
                {
                    "kiosk_backend_info": {
                        "token": token,
                        "company_id": company.id,
                        "company_name": company.name,
                        "departments": department_list,
                        "kiosk_mode": kiosk_mode,
                        "from_trial_mode": from_trial_mode,
                        "barcode_source": company.attendance_barcode_source,
                        "device_tracking_enabled": company.attendance_device_tracking,
                        "lang": py_to_js_locale(
                            company.partner_id.lang or company.env.lang
                        ),
                        "server_version_info": version_info.get("server_version_info"),
                    },
                },
            )

    @http.route(
        "/hr_attendance/attendance_employee_data", type="jsonrpc", auth="public"
    )
    def employee_attendance_data(self, token, employee_id):
        company = self._get_company(token)
        if company:
            employee = request.env["hr.employee"].sudo().browse(employee_id).exists()
            if employee and employee.company_id == company:
                return self._get_employee_info_response(employee)
        return {}

    @http.route(
        "/hr_attendance/attendance_barcode_scanned", type="jsonrpc", auth="public"
    )
    def scan_barcode(self, token, barcode):
        company = self._get_company(token)
        if company:
            employee = (
                request.env["hr.employee"]
                .sudo()
                .search(
                    [("barcode", "=", barcode), ("company_id", "=", company.id)],
                    limit=1,
                )
            )
            if employee:
                employee._attendance_action_change(
                    self._get_geoip_response(
                        "kiosk",
                        device_tracking_enabled=company.attendance_device_tracking,
                    )
                )
                return self._get_employee_info_response(employee)
        return {}

    @http.route("/hr_attendance/manual_selection", type="jsonrpc", auth="public")
    def manual_selection(
        self, token, employee_id, pin_code, latitude=False, longitude=False
    ):
        company = self._get_company(token)
        if company:
            employee = request.env["hr.employee"].sudo().browse(employee_id).exists()
            if (
                employee
                and employee.company_id == company
                and (
                    (not company.attendance_kiosk_use_pin)
                    or employee._check_attendance_pin(pin_code)
                )
            ):
                employee._attendance_action_change(
                    self._get_geoip_response(
                        "kiosk",
                        latitude=latitude,
                        longitude=longitude,
                        device_tracking_enabled=company.attendance_device_tracking,
                    )
                )
                return self._get_employee_info_response(employee)
        return {}

    @http.route("/hr_attendance/employees_infos", type="jsonrpc", auth="public")
    def employees_infos(self, token, limit, offset, domain):
        for condition in domain:
            if not isinstance(condition, (list, tuple)) or len(condition) != 3:
                continue
            field_name, operator, _value = condition
            if field_name not in ("name", "department_id") or operator not in (
                "=",
                "ilike",
            ):
                raise UserError(
                    _(
                        "Invalid domain, use 'name' and/or 'department_id' fields "
                        "with '=' and/or 'ilike' operators.",
                    )
                )

        company = self._get_company(token)
        if company:
            domain = Domain(domain) & Domain("company_id", "=", company.id)
            employees = (
                request.env["hr.employee"]
                .sudo()
                .search_fetch(
                    domain,
                    ["id", "display_name", "job_id"],
                    limit=limit,
                    offset=offset,
                    order="name, id",
                )
            )
            employees_data = [
                {
                    "id": employee.id,
                    "display_name": employee.display_name,
                    "job_id": employee.job_id.name,
                    "avatar": image_data_uri(employee.avatar_128),
                    "status": employee.attendance_state,
                    "mode": employee.last_attendance_id.in_mode,
                }
                for employee in employees
            ]
            return {
                "records": employees_data,
                "length": request.env["hr.employee"].sudo().search_count(domain),
            }
        return []

    @http.route("/hr_attendance/systray_check_in_out", type="jsonrpc", auth="user")
    def systray_attendance(self, latitude=False, longitude=False):
        employee = request.env.user.employee_id
        geo_ip_response = self._get_geoip_response(
            mode="systray",
            latitude=latitude,
            longitude=longitude,
            device_tracking_enabled=employee.company_id.attendance_device_tracking,
        )
        employee._attendance_action_change(geo_ip_response)
        return self._get_employee_info_response(employee)

    @http.route(
        "/hr_attendance/attendance_user_data",
        type="jsonrpc",
        auth="user",
        readonly=True,
    )
    def user_attendance_data(self):
        return request.env.user.employee_id._get_attendance_systray_data()

    def has_password(self):
        request.env.cr.execute(
            SQL(
                "SELECT password IS NOT NULL FROM res_users WHERE id = %(user_id)s",
                user_id=request.env.user.id,
            )
        )
        row = request.env.cr.fetchone()
        return bool(row and row[0])

    @http.route("/hr_attendance/set_settings", type="jsonrpc", auth="public")
    def set_attendance_settings(self, token, mode):
        company = self._get_company(token)
        if not company:
            return {}
        modes = dict(
            request.env["res.company"]._fields["attendance_kiosk_mode"].selection
        )
        if mode not in modes:
            return {"status": "error", "message": _("Unknown kiosk mode.")}
        try:
            request.env["res.company"].browse(company.id).attendance_kiosk_mode = mode
        except AccessError:
            return {
                "status": "error",
                "message": _("You are not allowed to change the kiosk settings."),
            }
        return {"status": "success"}
