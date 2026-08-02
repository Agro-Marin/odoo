#!/usr/bin/env python
# ruff: noqa: F821
# (ruff don't see read variables from release.py)

import pathlib

from setuptools import find_namespace_packages, setup

exec(
    (pathlib.Path(__file__).parent / "odoo" / "release.py")
    .open("rb")
    .read()
)  # Load release variables
lib_name = "odoo"

LONG_DESCRIPTION = """\
Odoo is a complete ERP and CRM. The main features are accounting (analytic
and financial), stock management, sales and purchases management, tasks
automation, marketing campaigns, help desk, POS, etc. Technical features include
a distributed server, an object database, a dynamic GUI,
customizable reports, and XML-RPC interfaces.
"""

CLASSIFIERS = [
    "Development Status :: 5 - Production/Stable",
    "Programming Language :: Python",
]

setup(
    name="odoo",
    version=version,
    description=description,
    long_description=LONG_DESCRIPTION,
    url=url,
    author=author,
    author_email="info@odoo.com",
    classifiers=CLASSIFIERS,
    license="LGPL-3.0-only",
    scripts=["setup/odoo"],
    packages=find_namespace_packages(include=["odoo*", "addons*"]),
    package_dir={"%s" % lib_name: "odoo"},
    include_package_data=True,
    install_requires=[
        "asn1crypto",
        "babel >= 1.0",
        "cbor2",
        "chardet",
        "cryptography",
        "docutils",
        "geoip2",
        "idna",
        "Jinja2",
        "lxml",  # windows binary http://www.lfd.uci.edu/~gohlke/pythonlibs/
        "lxml_html_clean",
        "MarkupSafe",
        "num2words",
        "ofxparse",
        "openpyxl",
        "pillow",  # windows binary http://www.lfd.uci.edu/~gohlke/pythonlibs/
        "polib",
        "protobuf",
        "psutil",  # windows binary code.google.com/p/psutil/downloads/list
        "psycopg[binary] >= 3.3.2",
        "pyopenssl",
        "pypdf",
        "pyserial",
        "python-dateutil",
        "python-stdnum",
        "pytz",
        "pyusb >= 1.0.0b1",
        "qrcode",
        "reportlab",  # windows binary pypi.python.org/pypi/reportlab
        "rjsmin",
        "requests",
        "urllib3",
        "vobject",
        "werkzeug",
        "xlsxwriter",
        "zeep",
    ],
    python_requires=">=" + ".".join(map(str, MIN_PY_VERSION)),
    extras_require={
        "ldap": ["python-ldap"],
    },
)
