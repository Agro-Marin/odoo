import requests
from urllib3.util.ssl_ import create_urllib3_context

from .structured_reference import *


class LegacyHTTPAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        OP_LEGACY_SERVER_CONNECT = 0x04
        context = create_urllib3_context(options=OP_LEGACY_SERVER_CONNECT)
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)
