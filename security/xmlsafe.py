"""Hardened XML parsing for Office documents.

Office Open XML never needs a DTD. Any DOCTYPE/ENTITY declaration is treated as an attack
(XXE file disclosure, "billion laughs" expansion) and rejected before parsing; the parser also
refuses entity resolution, DTD loading, network access and oversized trees.
"""
import re

from lxml import etree


class XMLSecurityError(ValueError):
    pass


_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False,
                          huge_tree=False)
_DECL = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


def fromstring(data: bytes):
    if _DECL.search(data):
        raise XMLSecurityError("XML with a DTD or entity declaration is not allowed")
    return etree.fromstring(data, _PARSER)
