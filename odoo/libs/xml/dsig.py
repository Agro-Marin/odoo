"""W3C XML-Signature (xmldsig) reference processing.

Shared primitives for the localizations that produce enveloped XAdES
signatures (ES TicketBAI, ES Facturae, EC, CO DIAN, ...). Each of them used to
carry a private copy of this algorithm in its own ``xml_utils.py``; the copies
had drifted, so fixes made in one never reached the others.

Spec references:
    - C14N 1.0: https://www.w3.org/TR/2001/REC-xml-c14n-20010315
    - Reference/URI: https://www.w3.org/TR/xmldsig-core/#sec-URI
    - Enveloped signature: https://www.w3.org/TR/xmldsig-core/#sec-EnvelopedSignature
    - DigestValue: https://www.w3.org/TR/xmldsig-core/#sec-DigestValue

The ``ds`` prefix is fixed here on purpose: the copies spelled the namespace
differently (``{'': ...}`` vs ``{'ds': ...}``) but every one of them resolved to
the same namespace URI, so the prefix was never semantic.
"""

import hashlib
from base64 import b64encode
from copy import deepcopy

from lxml import etree

DS_NS = "http://www.w3.org/2000/09/xmldsig#"
EXC_C14N_ALGORITHM = "http://www.w3.org/2001/10/xml-exc-c14n#"

_NSMAP = {"ds": DS_NS}


class XmlSigError(ValueError):
    """A signature Reference URI could not be resolved to exactly one node.

    Callers running inside the ORM are expected to catch this and re-raise it
    as a ``UserError``; this module stays free of Odoo imports so it can live
    in ``odoo.libs``.
    """


def canonicalize(
    node: etree._Element | str,
    *,
    exclusive: bool = False,
    inclusive_ns_prefixes: list[str] | None = None,
) -> bytes:
    """Return the canonical (C14N 1.0, no comments) representation of ``node``.

    :param node: An lxml element, or a string to be parsed as one.
    :param exclusive: Use exclusive canonicalization (xml-exc-c14n) instead of
        the inclusive default.
    :param inclusive_ns_prefixes: Prefixes to keep inclusive under exclusive
        c14n, i.e. the Transform's ``InclusiveNamespaces/@PrefixList``.
    :return: UTF-8 encoded bytes.
    """
    if isinstance(node, str):
        node = etree.fromstring(node)
    return etree.tostring(
        node,
        method="c14n",
        with_comments=False,
        exclusive=exclusive,
        inclusive_ns_prefixes=inclusive_ns_prefixes,
    )


def _c14n_params_from_transforms(reference: etree._Element) -> tuple[bool, list[str]]:
    """Read a Reference's Transform list to decide how to canonicalize it.

    A Reference that declares no exclusive-c14n Transform canonicalizes
    inclusively, which is what every localization except CO DIAN does.
    """
    transforms = reference.findall(".//{*}Transform")
    if not transforms or transforms[0].get("Algorithm") != EXC_C14N_ALGORITHM:
        return False, []
    prefix_list = []
    inclusive_ns = transforms[0].find(".//{*}InclusiveNamespaces")
    if inclusive_ns is not None and inclusive_ns.get("PrefixList"):
        prefix_list = inclusive_ns.get("PrefixList").split(" ")
    return True, prefix_list


def _enveloping_signatures(
    reference: etree._Element, copied_root: etree._Element
) -> list[etree._Element]:
    """Return the ``ds:Signature`` elements to strip for *reference*.

    They are located inside *copied_root*, the deep copy being canonicalized.

    xmldsig-core §6.6.4 defines the enveloped-signature transform as removing
    "the ``Signature`` element **containing** the ``Reference``" — its own, not
    every signature in the document. Removing all of them is indistinguishable
    on a singly-signed document and wrong on a co-signed one: each signer would
    digest a document with the *other* signatures stripped, while a verifier
    removes only the signature it is checking, so the digests never match and
    every signature after the first fails to verify.

    The signature is located in the caller's tree and re-found in
    ``copied_root`` by its **index in document order**, because the copy is a
    different object graph and identity does not survive ``deepcopy``. Index
    rather than ``getpath()``: that returns prefixed steps (``/doc/ds:Signature``)
    which the copy's evaluator cannot resolve without the original's prefix map,
    whereas a structural copy preserves document order exactly.

    Falls back to every signature when the reference has no ``Signature``
    ancestor (a detached signature, where there is nothing enveloping to
    remove): that keeps the previous behaviour for the shape it was correct for.
    """
    tag = f"{{{DS_NS}}}Signature"
    own = next(reference.iterancestors(tag), None)
    if own is None:
        return list(copied_root.iter(tag))

    originals = list(reference.getroottree().getroot().iter(tag))
    index = next((i for i, sig in enumerate(originals) if sig is own), None)
    if index is None:
        msg = "the reference's enveloping signature is not in its own document"
        raise XmlSigError(msg)

    copies = list(copied_root.iter(tag))
    if index >= len(copies):
        # Refusing beats digesting the wrong octets, which would produce a
        # signature nothing can verify.
        msg = f"signature {index} is missing from the copied document"
        raise XmlSigError(msg)
    return [copies[index]]


def resolve_reference(uri: str, reference: etree._Element, base_uri: str = "") -> bytes:
    """Return the canonicalized octet stream that ``uri`` identifies.

    Two forms are handled, per the xmldsig URI rules:

    - ``uri == base_uri`` (empty by default) means the whole document *with the
      signature removed* -- the enveloped-signature transform.
    - ``#foo`` is a same-document reference, matched case-sensitively against
      any attribute whose local name is ``Id``.

    The document is deep-copied before the signature is stripped, so the
    caller's tree is never mutated.

    :raise XmlSigError: if the URI resolves to zero or to several nodes.
    """
    exclusive, prefix_list = _c14n_params_from_transforms(reference)
    node = deepcopy(reference.getroottree().getroot())

    if uri == base_uri:
        for signature in _enveloping_signatures(reference, node):
            if signature.tail:
                if (previous := signature.getprevious()) is not None:
                    previous.tail = (previous.tail or "") + signature.tail
                else:
                    parent = signature.getparent()
                    parent.text = (parent.text or "") + signature.tail
            signature.getparent().remove(signature)
        return canonicalize(
            node, exclusive=exclusive, inclusive_ns_prefixes=prefix_list
        )

    if uri.startswith("#"):
        results = node.xpath('//*[@*[local-name() = "Id"]=$uri]', uri=uri.lstrip("#"))
        if len(results) == 1:
            return canonicalize(
                results[0], exclusive=exclusive, inclusive_ns_prefixes=prefix_list
            )
        if len(results) > 1:
            raise XmlSigError(
                f"Ambiguous reference URI {uri!r} resolved to {len(results)} nodes"
            )

    raise XmlSigError(f"URI {uri!r} not found")


def canonicalize_signed_info(signed_info: etree._Element) -> bytes:
    """Canonicalize ``ds:SignedInfo`` ahead of signing it.

    SignedInfo declares its own algorithm in ``ds:CanonicalizationMethod``,
    which is a separate choice from the per-Reference Transforms handled by
    :func:`resolve_reference` -- a document can canonicalize its references
    exclusively and its SignedInfo inclusively, or the reverse.

    https://www.w3.org/TR/xmldsig-core/#sec-SignedInfo
    """
    method = signed_info.find(".//{*}CanonicalizationMethod")
    exclusive = method is not None and method.get("Algorithm") == EXC_C14N_ALGORITHM
    prefix_list = []
    if exclusive:
        inclusive_ns = method.find(".//{*}InclusiveNamespaces")
        if inclusive_ns is not None and inclusive_ns.get("PrefixList"):
            prefix_list = inclusive_ns.get("PrefixList").split(" ")
    return canonicalize(
        signed_info, exclusive=exclusive, inclusive_ns_prefixes=prefix_list
    )


def fill_reference_digests(
    signed_info: etree._Element,
    base_uri: str = "",
    *,
    algorithm: str = "sha256",
) -> None:
    """Compute and write the DigestValue of every Reference under ``signed_info``.

    :param signed_info: The ``ds:SignedInfo`` element, modified in place.
    :param base_uri: The URI that denotes the whole document (usually empty).
    :param algorithm: ``hashlib`` digest name. The localizations differ here --
        EC signs with sha1, the others with sha256 -- so it has no safe default
        beyond the most common one and callers should pass it explicitly.
    """
    for reference in signed_info.findall("ds:Reference", namespaces=_NSMAP):
        octets = resolve_reference(reference.get("URI", ""), reference, base_uri)
        digest = hashlib.new(algorithm, octets).digest()
        reference.find("ds:DigestValue", namespaces=_NSMAP).text = b64encode(digest)
