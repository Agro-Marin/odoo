from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Self

from odoo.libs.settings import OptionSource, SettingsSlot

__all__ = [
    "INHERIT_FROM_CRON",
    "ServerSettings",
    "current",
    "installed",
    "override",
    "slot",
]

INHERIT_FROM_CRON = -1


def _is_inherited(limit: int) -> bool:
    return limit <= INHERIT_FROM_CRON


def _first_owned(*limits: int) -> int:
    limit = limits[0]
    for candidate in limits[1:]:
        if not _is_inherited(limit):
            break
        limit = candidate
    return limit


def _is_socket_activated(config: OptionSource) -> bool:
    return bool(
        config["http_enable"]
        and os.getenv("LISTEN_FDS") == "1"
        and os.getenv("LISTEN_PID") == str(os.getpid())
    )


@dataclass(frozen=True, slots=True)
class ServerSettings:
    workers: int = 0
    http_enable: bool = True
    http_interface: str = "0.0.0.0"
    http_port: int = 8069
    gevent_port: int = 8072
    http_socket_activation: bool = False
    max_cron_threads: int = 2
    job_workers: int = 1
    limit_request: int = 2**16
    limit_time_real: int = 120
    limit_time_real_cron: int = INHERIT_FROM_CRON
    limit_time_real_job: int = INHERIT_FROM_CRON
    limit_time_cpu: int = 60
    limit_time_worker_cron: int = 0
    limit_time_worker_job: int = INHERIT_FROM_CRON
    limit_memory_soft: int = 2048 * 1024 * 1024
    limit_memory_soft_gevent: int = 0
    dev_mode: tuple[str, ...] = ()
    test_enable: bool = False
    test_tags: str = ""
    db_name: tuple[str, ...] = ()
    dbfilter: str = ""
    data_dir: str = ""
    server_wide_modules: tuple[str, ...] = ()
    init: tuple[str, ...] = ()
    update: tuple[str, ...] = ()
    reinit: tuple[str, ...] = ()
    db_maxconn: int = 64
    db_maxconn_gevent: int = 0
    db_port: int | None = None
    registry_idle_timeout: int = 0

    @classmethod
    def from_config(cls, config: OptionSource) -> Self:
        return cls(
            workers=int(config["workers"] or 0),
            http_enable=bool(config["http_enable"]),
            http_interface=config["http_interface"] or "0.0.0.0",
            http_port=int(config["http_port"]),
            gevent_port=int(config["gevent_port"]),
            http_socket_activation=_is_socket_activated(config),
            max_cron_threads=int(config["max_cron_threads"] or 0),
            job_workers=int(config["job_workers"] or 0),
            limit_request=int(config["limit_request"] or 0),
            limit_time_real=int(config["limit_time_real"]),
            limit_time_real_cron=int(config["limit_time_real_cron"]),
            limit_time_real_job=int(config["limit_time_real_job"]),
            limit_time_cpu=int(config["limit_time_cpu"]),
            limit_time_worker_cron=int(config["limit_time_worker_cron"]),
            limit_time_worker_job=int(config["limit_time_worker_job"]),
            limit_memory_soft=int(config["limit_memory_soft"] or 0),
            limit_memory_soft_gevent=int(config["limit_memory_soft_gevent"] or 0),
            dev_mode=tuple(config["dev_mode"] or ()),
            test_enable=bool(config["test_enable"]),
            test_tags=str(config["test_tags"] or ""),
            db_name=tuple(config["db_name"] or ()),
            dbfilter=config["dbfilter"] or "",
            data_dir=str(config["data_dir"] or ""),
            server_wide_modules=tuple(config["server_wide_modules"] or ()),
            init=tuple(config["init"] or ()),
            update=tuple(config["update"] or ()),
            reinit=tuple(config["reinit"] or ()),
            db_maxconn=int(config["db_maxconn"]),
            db_maxconn_gevent=int(config["db_maxconn_gevent"] or 0),
            db_port=int(config["db_port"]) if config["db_port"] else None,
            registry_idle_timeout=int(config["registry_idle_timeout"] or 0),
        )

    @property
    def job_max_age(self) -> int:
        return _first_owned(self.limit_time_worker_job, self.limit_time_worker_cron)

    @property
    def cron_real_time_budget(self) -> float:
        return max(_first_owned(self.limit_time_real_cron, self.limit_time_real), 0)

    @property
    def job_real_time_budget(self) -> float:
        return max(
            _first_owned(
                self.limit_time_real_job,
                self.limit_time_real_cron,
                self.limit_time_real,
            ),
            0,
        )

    @property
    def update_module(self) -> bool:
        return bool(self.init or self.update or self.reinit)


def _from_live_config() -> ServerSettings:
    import odoo.tools

    return ServerSettings.from_config(odoo.tools.config)


slot: SettingsSlot[ServerSettings] = SettingsSlot("odoo.service", _from_live_config)
current = slot.current
installed = slot.installed
override = slot.override
