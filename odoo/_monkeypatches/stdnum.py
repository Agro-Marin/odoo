_soap_clients = {}


def new_get_soap_client(wsdlurl, timeout=30):
    if (wsdlurl, timeout) not in _soap_clients:
        transport = None
        try:
            from zeep.transports import Transport

            transport = Transport(operation_timeout=timeout, timeout=timeout)
            from zeep import CachingClient

            client = CachingClient(wsdlurl, transport=transport).service
        except ImportError:
            try:
                if transport is None:
                    msg = "zeep.transports is unavailable"
                    raise ImportError(msg)
                from zeep import Client

                client = Client(wsdlurl, transport=transport).service
            except ImportError:
                try:
                    from urllib import getproxies
                except ImportError:
                    from urllib.request import getproxies
                try:
                    from suds.client import Client

                    client = Client(
                        wsdlurl, proxy=getproxies(), timeout=timeout
                    ).service
                except ImportError:
                    try:
                        from pysimplesoap.client import SoapClient

                        client = SoapClient(
                            wsdl=wsdlurl, proxy=getproxies(), timeout=timeout
                        )
                    except ImportError:
                        raise ImportError(
                            "No SOAP library (such as zeep) found"
                        ) from None
        _soap_clients[(wsdlurl, timeout)] = client
    return _soap_clients[(wsdlurl, timeout)]


def patch_module() -> None:
    from importlib.metadata import PackageNotFoundError, version

    from odoo.libs.parse_version import parse_version

    try:
        stdnum_version = version("python-stdnum")
    except PackageNotFoundError:
        stdnum_version = "0"
    if parse_version(stdnum_version) >= parse_version("2.0"):
        return

    try:
        from stdnum import util
    except ImportError:
        return

    util.get_soap_client = new_get_soap_client
