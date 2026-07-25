"""Odoo's hardened lxml default parsers.

Importing this module installs process-wide lxml defaults:

* ``resolve_entities=False`` -- the XXE guard, so parsing an attacker-supplied
  document (an imported XML data file, an uploaded UBL/CII invoice, an EDI
  payload, a SOAP response) with a bare ``etree.fromstring(data)`` cannot expand
  an external entity into a local file read or a network fetch.
* ``decompress=False`` -- refuses transparently gzipped input, a
  decompression-bomb guard.

Both are **defence in depth, not a live patch**: on the lxml this fork pins
(6.0.2, verified) the library already refuses both by default -- entity
resolution has been off since lxml 5.0, and stream decompression is likewise
refused. Pinning them explicitly is what keeps that true across an lxml
downgrade, a differently-configured build, or a future default flip; do not read
this module as evidence that unhardened parsing is currently exploitable.

It lives here, next to the XML layer it applies to, because it is a **global
mutation of a third-party library** that every ``etree`` caller in the process
inherits.  It used to sit in ``odoo.tools.misc``, a module whose own docstring
declares it a deprecated compatibility shim -- so a process-wide policy was
applied as a side effect of importing something new code is told not to import,
and code reaching lxml without ``odoo.tools`` in its import graph (a standalone
script, the database-free test suites, anything importing ``odoo.libs.xml``
directly) silently did not get it.  ``odoo.libs.xml`` is the layer such code
already depends on, so the policy now travels with it.

``odoo.tools.misc`` re-exports ``default_parser`` from here, so nothing that
relied on the old location changes.
"""

from lxml import etree, objectify

__all__ = ["default_parser"]

etree.set_default_parser(etree.XMLParser(resolve_entities=False, decompress=False))

default_parser = etree.XMLParser(
    resolve_entities=False, remove_blank_text=True, decompress=False
)
default_parser.set_element_class_lookup(objectify.ObjectifyElementClassLookup())
objectify.set_default_parser(default_parser)
