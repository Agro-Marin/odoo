import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from werkzeug.exceptions import HTTPException, NotFound

from odoo import http
from odoo.exceptions import AccessDenied, AccessError, MissingError, UserError
from odoo.http import SessionExpiredException, request

from odoo.addons.mail.controllers.thread import ThreadController
from odoo.addons.mail.controllers.utils import to_record_id
from odoo.addons.mail.tools.discuss import Store, add_guest_to_context

_logger = logging.getLogger(__name__)

PROPAGATED_BATCH_ERRORS = (
    HTTPException,
    SessionExpiredException,
    AccessError,
    AccessDenied,
)


class WebclientController(ThreadController):
    @http.route("/mail/action", methods=["POST"], type="jsonrpc", auth="public")
    @add_guest_to_context
    def mail_action(
        self, fetch_params: list[str | list], context: dict | None = None
    ) -> dict:
        return self._process_request(fetch_params, context=context)

    @http.route(
        "/mail/data", methods=["POST"], type="jsonrpc", auth="public", readonly=True
    )
    @add_guest_to_context
    def mail_data(
        self, fetch_params: list[str | list], context: dict | None = None
    ) -> dict:
        return self._process_request(fetch_params, context=context)

    @classmethod
    def _process_request(
        cls, fetch_params: list[str | list], context: dict | None
    ) -> dict:
        cls._update_context_from_client(context)
        if request.env.cr.readonly:
            store = Store()

            def answer_whole_batch() -> None:
                with request.env.cr.savepoint():
                    request.update_context(mail_fetch_batched=True)
                    try:
                        cls._process_request_loop(store, fetch_params)
                    finally:
                        request.update_context(mail_fetch_batched=False)

            if cls._absorbing_failure(
                answer_whole_batch,
                missing="Batched fetch needed a record that no longer exists; "
                "answering each param in isolation.",
                failed="Batched fetch failed; answering each param in isolation.",
                traceback=False,
            ):
                return store.get_result()
        store = Store()
        cls._process_request_loop(store, fetch_params)
        return store.get_result()

    @classmethod
    def _process_request_loop(
        cls, store: Store, fetch_params: list[str | list]
    ) -> None:
        if isinstance(fetch_params, str) or not isinstance(fetch_params, (list, tuple)):
            raise NotFound
        for fetch_param in fetch_params:
            name, params, data_id = (
                (fetch_param, None, None)
                if isinstance(fetch_param, str)
                else (list(fetch_param) + [None, None])[:3]
            )
            store.data_id = data_id
            cls._process_one_request(store, name, params)
        store.data_id = None

    @classmethod
    def _dispatch_one_request(cls, store: Store, name: str, params: Any) -> None:
        cls._process_request_for_all(store, name, params)
        if not request.env.user._is_public():
            cls._process_request_for_logged_in_user(store, name, params)
        if request.env.user._is_internal():
            cls._process_request_for_internal_user(store, name, params)

    @staticmethod
    def _absorbing_failure(
        work: Callable[[], None], *, missing: str, failed: str, traceback: bool
    ) -> bool:
        try:
            work()
        except PROPAGATED_BATCH_ERRORS:
            raise
        except MissingError:
            _logger.info(missing)
        except UserError:
            raise
        except Exception:
            _logger.log(
                logging.ERROR if traceback else logging.INFO, failed, exc_info=True
            )
        else:
            return True
        return False

    @classmethod
    def _process_one_request(cls, store: Store, name: str, params: Any) -> None:
        def answer_one_param() -> None:
            with request.env.cr.savepoint():
                cls._dispatch_one_request(store, name, params)

        cls._absorbing_failure(
            answer_one_param,
            missing=f"Discarding fetch param {name!r}: a record it needed no longer "
            f"exists.",
            failed=f"Discarding fetch param {name!r}: it failed while the rest of the "
            f"batch is answered normally.",
            traceback=True,
        )

    @classmethod
    def _process_request_for_all(cls, store: Store, name: str, params: Any) -> None:
        if name == "init_messaging":
            if not request.env.user._is_public():
                user = request.env.user.sudo(False)
                user._init_messaging(store)
        if name == "mixin.mail.thread":
            cls._add_thread_fetch_param(store, params)

    @classmethod
    def _add_thread_fetch_param(cls, store: Store, params: Any) -> None:
        try:
            thread = cls._get_thread_with_access(
                params["thread_model"],
                params["thread_id"],
                mode="read",
                **params.get("access_params", {}),
            )
        except NotFound:
            _logger.info(
                "Discarding a thread fetch param naming an unusable model: %r",
                params.get("thread_model") if isinstance(params, dict) else params,
            )
            return
        if not thread:
            store.add(
                request.env[params["thread_model"]].browse(
                    to_record_id(params["thread_id"])
                ),
                {"hasReadAccess": False, "hasWriteAccess": False},
                as_thread=True,
            )
        else:
            store.add(thread, request_list=params["request_list"], as_thread=True)

    @classmethod
    def _process_request_for_logged_in_user(
        cls, store: Store, name: str, params: Any
    ) -> None:
        if name == "failures":
            domain = [
                ("author_id", "=", request.env.user.partner_id.id),
                ("notification_status", "in", ("bounce", "exception")),
                ("mail_message_id.message_type", "!=", "user_notification"),
                ("mail_message_id.model", "!=", False),
                ("mail_message_id.res_id", "!=", 0),
            ]
            notifications = (
                request.env["mail.notification"].sudo().search(domain, limit=100)
            )
            found = defaultdict(list)
            for message in notifications.mail_message_id:
                found[message.model].append(message.res_id)
            existing = {
                model: set(request.env[model].browse(ids).exists().ids)
                for model, ids in found.items()
                if model in request.env
            }
            valid = notifications.filtered(
                lambda n: (
                    n.mail_message_id.res_id
                    in existing.get(n.mail_message_id.model, ())
                )
            )
            lost = notifications - valid
            if lost and not request.env.cr.readonly:
                lost.sudo().unlink()
            valid.mail_message_id._message_notifications_to_store(store)

    @classmethod
    def _process_request_for_internal_user(
        cls, store: Store, name: str, params: Any
    ) -> None:
        if name == "systray_get_activities":
            bus_last_id = request.env["bus.bus"].sudo()._bus_last_id()
            groups = request.env["res.users"]._get_activity_groups()
            store.add_global_values(
                activityCounter=sum(group.get("due_count", 0) for group in groups),
                activity_counter_bus_id=bus_last_id,
                activityGroups=groups,
            )
        if name == "mail.canned.response":
            domain = [
                "|",
                ("create_uid", "=", request.env.user.id),
                ("group_ids", "in", request.env.user.all_group_ids.ids),
            ]
            store.add(request.env["mail.canned.response"].search(domain))
        if name == "avatar_card":
            record_id, model = params.get("id"), params.get("model")
            if not record_id or model not in ("res.users", "res.partner"):
                return
            context = {
                "active_test": False,
                "allowed_company_ids": request.env.user._get_company_ids(),
            }
            record = (
                request.env[model]
                .with_context(**context)
                .search([("id", "=", record_id)])
            )
            store.add(record, record._get_store_avatar_card_fields(store.target))
