import socket

import pytest

import odoo.init  # noqa: F401  imported for the bootstrap side effect
from odoo.libs import netguard
from odoo.tests import transaction_case


def _addresses(infos):
    return {info[4][0] for info in infos}


def test_hosts_file_names_skip_addresses_and_comments(tmp_path):
    hosts = tmp_path / "hosts"
    hosts.write_text(
        "127.0.0.1 localhost\n"
        "::1 IP6-Localhost ip6-loopback  # the IPv6 loopback\n"
        "# 10.0.0.1 commented.example\n"
        "\n",
        encoding="utf-8",
    )
    assert transaction_case._hosts_file_names(str(hosts)) == {
        "localhost",
        "ip6-localhost",
        "ip6-loopback",
    }


def test_a_missing_hosts_file_names_nothing(tmp_path):
    assert transaction_case._hosts_file_names(str(tmp_path / "absent")) == set()


def test_an_external_name_gets_the_public_test_address():
    infos = transaction_case._offline_getaddrinfo(
        "erp.example.com", 443, type=socket.SOCK_STREAM
    )
    assert _addresses(infos) == {transaction_case._EXTERNAL_TEST_ADDRESS}


@pytest.mark.skipif(
    "ip6-localhost" not in transaction_case._hosts_file_names(),
    reason="this machine's hosts file does not name ip6-localhost",
)
def test_a_hosts_file_loopback_name_stays_loopback_for_the_egress_guard():
    infos = transaction_case._offline_getaddrinfo(
        "ip6-localhost", 8069, type=socket.SOCK_STREAM
    )
    assert _addresses(infos) == {"::1"}
    with pytest.raises(netguard.DestinationRefused):
        netguard.check_host(
            "ip6-localhost",
            8069,
            policy=netguard.PUBLIC_ONLY,
            resolver=transaction_case._offline_getaddrinfo,
        )
