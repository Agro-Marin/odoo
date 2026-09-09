import hashlib
import io
import itertools
import json
import logging
import pathlib
import pprint
import re
import textwrap
import zipfile

import werkzeug
from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import Response, Stream, request
from odoo.modules import get_module_path
from odoo.modules.module import Manifest
from odoo.tools.misc import str2bool

_logger = logging.getLogger(__name__)

_iot_logger = logging.getLogger(__name__ + ".iot_log")
# We want to catch any log level that the IoT send
_iot_logger.setLevel(logging.DEBUG)

_logger = logging.getLogger(__name__)


def ensure_unique_name(name):
    existing_names = (
        request.env["iot.box"]
        .sudo()
        .search([("name", "ilike", name + "%")])
        .mapped("name")
    )
    base_name = name
    suffix = 1
    while name in existing_names:
        name = f"{base_name} ({suffix})"
        suffix += 1

    return name


class IoTBoxLookup:
    """Resolving a box from the identifier it reports, shared by the controllers
    a box talks to. Not an ``http.Controller`` itself: it declares no route and
    must not have any inherited into it."""

    def _search_box(self, identifier):
        return (
            request.env["iot.box"]
            .sudo()
            .search([("identifier", "=", identifier)], limit=1)
        )


class IoTController(IoTBoxLookup, http.Controller):
    def _get_handler_modules(self, box):
        """Names of the modules whose ``iot_handlers/`` ship to ``box``.

        Two manifest keys let a module opt out of the default "installed means
        shipped" rule. ``iot_handlers_always`` ships a driver even when nobody
        has installed it, so the box can report a device the database cannot yet
        act on. ``iot_handlers_in_image`` marks a driver a dated box image
        already carries from git; re-sending it would overwrite the git copy
        with the database's, so those are withheld from such boxes and custom
        drivers still travel.
        """
        installed = set(
            request.env["ir.module.module"]
            .sudo()
            .search([("state", "=", "installed")])
            .mapped("name")
        )
        always, in_image = set(), set()
        for manifest in Manifest.all_addon_manifests():
            if manifest["iot_handlers_always"]:
                always.add(manifest.name)
            if manifest["iot_handlers_in_image"]:
                in_image.add(manifest.name)

        modules = installed | always | {"iot_drivers"}
        if re.search(r"\d{4}\.\d{2}\.\d{2}", box.version):
            modules -= in_image

        # `iot_drivers` ships to every box, dated image or not, and the old
        # blocklist this replaced withheld it from dated ones. The box makes
        # that unsafe: `download_iot_handlers` calls `delete_iot_handlers`
        # first, which empties the whole handler directory, and only then
        # extracts. Withholding a module therefore DELETES its handlers rather
        # than preserving the git copy the blocklist's comment claimed to
        # protect, and the git checkout that could restore them runs earlier in
        # the same boot and only when the branch changed. A box that lost the
        # driver framework this way has no drivers at all.
        return sorted(modules | {"iot_drivers"})

    @http.route("/iot/get_handlers", type="http", auth="public", csrf=False)
    def get_handlers(self, identifier, auto):
        """Return a zip file containing all the IoT handlers for the given IoT Box.

        :param identifier: The identifier of the IoT Box.
        :param auto: If True, the IoT Box will automatically update its handlers.
        :return: A zip file containing all the IoT handlers.
        """
        # Check if identifier is of one of the IoT Boxes
        box = self._search_box(identifier)
        if not box or (auto == "True" and not box.drivers_auto_update):
            raise werkzeug.exceptions.Unauthorized(
                description="No IoT box found with identifier '%s' or auto update disabled on the box."
                % identifier
            )

        # '_L.py' files for Linux and '_W.py' for Windows
        incompatible_filename = "_L.py" if box.version[0] == "W" else "_W.py"
        modules = self._get_handler_modules(box)

        fobj = io.BytesIO()
        with zipfile.ZipFile(fobj, "w", zipfile.ZIP_DEFLATED) as zf:
            for module in modules:
                module_path = get_module_path(module)
                if module_path:
                    iot_handlers = pathlib.Path(module_path) / "iot_handlers"
                    for handler in iot_handlers.glob("*/*"):
                        if handler.name.startswith((".", "_")) or handler.name.endswith(
                            incompatible_filename
                        ):
                            continue
                        zf.write(
                            handler, handler.relative_to(iot_handlers)
                        )  # In order to remove the absolute path

        etag = hashlib.sha256(fobj.getvalue()).hexdigest()
        # If the file has not been modified since the last request, return a 304 (Not Modified)
        if etag == request.httprequest.headers.get("If-None-Match"):
            return request.prepare_response("", headers=[("ETag", etag)], status=304)

        return Stream(
            type="data",
            data=fobj.getvalue(),
            download_name="iot_handlers.zip",
            etag=etag,
            size=fobj.tell(),
            public=True,
        ).get_response()

    @http.route("/iot/keyboard_layouts", type="http", auth="public", csrf=False)
    def load_keyboard_layouts(self, available_layouts):
        if not request.env["iot.keyboard.layout"].sudo().search_count([], limit=1):
            request.env["iot.keyboard.layout"].sudo().create(
                json.loads(available_layouts)
            )
        return ""

    @http.route("/iot/box/<string:identifier>/display_url", type="http", auth="public")
    def get_url(self, identifier):
        urls = {}
        iotbox = self._search_box(identifier)
        if iotbox:
            iot_devices = iotbox.device_ids.filtered(
                lambda device: device.type == "display"
            )
            for device in iot_devices:
                urls[device.identifier] = device.display_url
        return request.prepare_json_response(urls)

    @http.route("/iot/box/send_websocket", type="jsonrpc", auth="public")
    def iot_box_send_websocket(
        self, session_id, iot_box_identifier, device_identifier, status, **kwargs
    ):
        """Called by the IoT Box once an operation is over. We then forward
        the acknowledgment to the user who made the request to inform him
        of the success of the operation.

        :param session_id: ID of the operation
        :param iot_box_identifier: The IP of the IoT box (used to find the box)
        :param device_identifier: The IoT device identifier
        :param status: Status of the last action (success, error, ...)
        :param kwargs:
        """
        box = self._search_box(iot_box_identifier)
        if not box:
            _logger.warning(
                "No IoT Box found with identifier: '%s'. Request ignored",
                iot_box_identifier,
            )
            return

        if (
            device_identifier
            and not request.env["iot.device"]
            .sudo()
            .search(
                [("identifier", "=", device_identifier), ("iot_id", "=", box.id)],
                limit=1,
            )
            and device_identifier != box.identifier  # target the box itself
        ):
            _logger.warning(
                "No IoT device found with identifier '%s' (iot_box_identifier: %s). Request ignored",
                device_identifier,
                iot_box_identifier,
            )
            return

        request.env["iot.channel"].send_message(
            {
                "session_id": session_id
                or kwargs.get(
                    "owner"
                ),  # TODO: replace "owner" by "session_id" in drivers
                "iot_box_identifier": iot_box_identifier,
                "device_identifier": device_identifier,
                "message": {
                    "status": status,
                    "result": kwargs.get("result", {}),
                    "action_args": kwargs.get("action_args", {}),
                },
            },
            message_type="operation_confirmation",
        )

    @http.route("/iot/box/webrtc_answer", type="jsonrpc", auth="public")
    def iot_box_webrtc_answer(self, iot_box_identifier, answer):
        """Called by the IoT Box after receiving a WebRTC offer from a user.
        The IoT box sends its WebRTC answer and we forward it to the user so
        they can establish the connection.

        :param iot_box_identifier: The identifier (serial number) of the IoT box
        :param answer: The WebRTC answer object
        """
        box = self._search_box(iot_box_identifier)
        if not box:
            _logger.warning(
                "No IoT Box found with identifier: '%s'. Request ignored",
                iot_box_identifier,
            )
            raise NotFound()

        request.env["iot.channel"].send_message(
            {
                "iot_box_identifier": iot_box_identifier,
                "answer": answer,
            },
            message_type="webrtc_answer",
        )

    @http.route("/iot/setup", type="jsonrpc", auth="public")
    def update_box(self, iot_box, devices):
        """This function receives a dict from the iot box with information from it
        as well as devices connected and supported by this box.
        This function create the box and the devices and set the status (connected / disconnected)
         of devices linked with this box

        :param dict iot_box: IoT Box information
        :param dict devices: IoT devices information
        :return: IoT websocket channel
        """
        box = self._upsert_box(iot_box)
        if not box:
            return None

        _logger.info("IoT %s devices:\n%s", box, pprint.pformat(devices))
        self._upsert_devices(box, devices)
        return request.env["iot.channel"].sudo().get_iot_channel()

    def _upsert_box(self, iot_box):
        """Create or update the ``iot.box`` record this payload describes.

        Returns an empty recordset when the box is unknown and carries a token
        the database did not hand out, which is what stops a stranger enrolling
        itself.
        """
        iot_identifier = iot_box["identifier"]
        new_iot_ip = iot_box["ip"]
        new_iot_version = iot_box["version"]
        box = self._search_box(iot_identifier) or self._search_box(iot_box.get("mac"))
        create_update_value = {
            "identifier": iot_identifier,  # Ensure upgrade from MAC to serial number
            "ip": new_iot_ip,
            "version": new_iot_version,
        }
        if box:
            if (box.identifier, box.ip, box.version) != (
                iot_identifier,
                new_iot_ip,
                new_iot_version,
            ):
                _logger.info("Updating IoT %s with data: %s", box, create_update_value)
                box.write(create_update_value)
            return box

        icp_sudo = request.env["ir.config_parameter"].sudo()
        iot_token = icp_sudo.get_param("iot.iot_token")
        if not iot_token or iot_token != iot_box["token"]:
            _logger.warning(
                "Token mismatch for IoT %s expected %s got %s",
                iot_identifier,
                iot_token,
                iot_box["token"],
            )
            return request.env["iot.box"]

        name = "IoT Box" if new_iot_version.startswith("L") else "Virtual IoT Box"
        create_update_value["name"] = ensure_unique_name(name)
        _logger.info("Creating IoT with data: %s", create_update_value)
        box = request.env["iot.box"].sudo().create(create_update_value)
        # Clear the used token to force creating a new one for next IoT Box
        icp_sudo.set_param("iot.iot_token", "")
        return box

    def _find_moved_device(self, known, device_identifier, data_device):
        """A device already on record whose identifier has changed underneath it.

        A serial device is identified by the port it answers on, so replugging
        it into another port reads as a brand new device and the old record is
        left behind marked disconnected. Returning the old record here re-points
        it instead. A driver module overrides this when it can recognise its own
        hardware across such a move.

        The Belgian fiscal data module is the one case the base app carries,
        rather than ``iot_blackbox_be``, because the heuristic has to hold on
        databases that never install that module.
        """
        if (
            data_device["type"] == "fiscal_data_module"
            and "BODO001" in data_device["name"]
        ):
            return known.filtered(
                lambda device: (
                    device.type == "fiscal_data_module"
                    and "BODO001" in (device.name or "")
                )
            )[:1]
        return known.browse()

    def _upsert_devices(self, box, devices):
        """Record the devices a box reports, and disconnect the ones it did not."""
        Device = request.env["iot.device"].sudo()
        known = Device.search([("iot_id", "=", box.id)])
        by_identifier = {device.identifier: device for device in known}
        previously_connected = known.filtered(
            lambda device: device.connected_status == "connected"
        )
        available_types = {s[0] for s in Device._fields["type"].selection}
        available_connections = {s[0] for s in Device._fields["connection"].selection}

        connected = Device
        for device_identifier, data_device in devices.items():
            if (
                data_device["type"] not in available_types
                or data_device["connection"] not in available_connections
            ):
                continue

            moved = self._find_moved_device(known, device_identifier, data_device)
            if moved:
                moved.write({"identifier": device_identifier})
                connected |= moved
                continue

            device = by_identifier.get(device_identifier, Device)
            if not device:
                device = Device.create(
                    {
                        "iot_id": box.id,
                        "name": data_device["name"],
                        "identifier": device_identifier,
                        "type": data_device["type"],
                        "manufacturer": data_device.get("manufacturer"),
                        "connection": data_device["connection"],
                        "subtype": data_device.get("subtype", ""),
                    }
                )
            elif device.type != data_device.get("type") or (
                device.subtype == "" and device.type == "printer"
            ):
                device.write(
                    {
                        "name": data_device.get("name"),
                        "type": data_device.get("type"),
                        "manufacturer": data_device.get("manufacturer"),
                        "subtype": data_device.get("subtype", ""),
                    }
                )
            connected |= device

        # Mark the received devices as connected, disconnect the others.
        connected.write({"connected_status": "connected"})
        (previously_connected - connected).write({"connected_status": "disconnected"})

    @http.route("/iot/box/update_certificate_status", type="jsonrpc", auth="public")
    def update_certificate_status(self, identifier, ssl_certificate_end_date):
        """Update the SSL certificate end date for the IoT Box.

        :param str identifier: IoT Box identifier
        :param str ssl_certificate_end_date: SSL certificate end date
        """
        box = self._search_box(identifier)
        if not box:
            _logger.warning(
                "No IoT Box found with identifier '%s'. Request ignored", identifier
            )
            return

        box.write({"ssl_certificate_end_date": ssl_certificate_end_date})


class IoTLogController(IoTBoxLookup, http.Controller):
    def _is_iot_log_enabled(self):
        return str2bool(
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("iot.should_log_iot_logs", True)
        )

    @http.route("/iot/log", type="http", auth="public", csrf=False)
    def receive_iot_log(self):
        IOT_ELEMENT_SEPARATOR = b"<log/>\n"
        IOT_LOG_LINE_SEPARATOR = b","
        IOT_IDENTIFIER_PREFIX = b"identifier "

        def log_line_transformation(log_line):
            split = log_line.split(IOT_LOG_LINE_SEPARATOR, 1)
            return {
                "levelno": int(split[0]),
                "line_formatted": split[1].decode("utf-8"),
            }

        def log_current_level():
            _iot_logger.log(
                log_level,
                "%s%s",
                init_log_message,
                textwrap.indent("\n".join(["", *log_lines]), " | "),
            )

        def finish_request():
            return Response(status=200)

        if not self._is_iot_log_enabled():
            return finish_request()

        request_data = request.httprequest.get_data()
        if request_data.endswith(IOT_ELEMENT_SEPARATOR):
            # Do not use rstrip as some characters of the separator might be at the end of the log line
            request_data = request_data[: -len(IOT_ELEMENT_SEPARATOR)]
        request_data_split = request_data.split(IOT_ELEMENT_SEPARATOR)
        if len(request_data_split) < 2:
            return finish_request()

        identifier_details = request_data_split.pop(0)
        if not identifier_details.startswith(IOT_IDENTIFIER_PREFIX):
            return finish_request()

        identifier = identifier_details[len(IOT_IDENTIFIER_PREFIX) :]
        iot_box = self._search_box(identifier)
        if not iot_box:
            return finish_request()

        log_details = map(log_line_transformation, request_data_split)
        init_log_message = "IoT box log '%s' #%d received:" % (iot_box.name, iot_box.id)

        for log_level, log_group in itertools.groupby(
            log_details, key=lambda log: log["levelno"]
        ):
            log_lines = [log_line["line_formatted"] for log_line in log_group]
            log_current_level()

        return finish_request()
