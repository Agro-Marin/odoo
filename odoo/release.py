from typing import Final

ALPHA, BETA, RELEASE_CANDIDATE, FINAL = "alpha", "beta", "candidate", "final"
RELEASE_LEVELS: Final[list[str]] = [ALPHA, BETA, RELEASE_CANDIDATE, FINAL]
RELEASE_LEVELS_DISPLAY: Final[dict[str, str]] = {
    ALPHA: "a",
    BETA: "b",
    RELEASE_CANDIDATE: "rc",
    FINAL: "",
}

# version_info format: (MAJOR, MINOR, MICRO, RELEASE_LEVEL, SERIAL, SUFFIX)
# inspired by Python's own sys.version_info, in order to be
# properly comparable using normal operators, for example:
#  (6,1,0,'beta',0) < (6,1,0,'candidate',1) < (6,1,0,'candidate',2)
#  (6,1,0,'candidate',2) < (6,1,0,'final',0) < (6,1,2,'final',0)
# NOTE: during release, the MAJOR version can become an arbitrary string ('saas~xx')
version_info: Final[tuple[int, int, int, str, int, str]] = (19, 0, 0, FINAL, 0, "")
series: str = ".".join(str(s) for s in version_info[:2])
serie = major_version = series
version: str = (
    series
    + RELEASE_LEVELS_DISPLAY[version_info[3]]
    + str(version_info[4] or "")
    + version_info[5]
)

product_name: Final[str] = "Odoo"
description: Final[str] = "Odoo Server"
url: Final[str] = "https://www.odoo.com"
author: Final[str] = "Odoo S.A."

nt_service_name: str = "odoo-server-" + series.replace("~", "-")

MIN_PY_VERSION: Final[tuple[int, int]] = (3, 14)
MAX_PY_VERSION: Final[tuple[int, int]] = (3, 14)
MIN_PG_VERSION: Final[int] = 18
