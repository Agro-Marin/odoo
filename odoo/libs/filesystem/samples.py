"""Minimal, valid bodies for the formats `guess_mimetype` identifies.

Reference data of this area rather than scaffolding of one suite: the sniffing
rules are only meaningful against real headers, and three addon test suites need
a payload a `Binary` field will accept. They lived in
`tests/test_mimetypes_guess.py`, which put every consumer outside `odoo.libs`
in breach of the area boundary -- `libs_facade_check` reports an addon that
reaches past an area, and importing a *test* module was the way past it.

Base64 text except where a format is only interesting unencoded
(`NAMESPACED_SVG`, `XML`, `TXT`), which is why the types are mixed; each is kept
exactly as the mimetype suite has always asserted against it.
"""

PNG = b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVQI12P4//8/AAX+Av7czFnnAAAAAElFTkSuQmCC"
GIF = b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs="
BMP = b"""Qk1+AAAAAAAAAHoAAABsAAAAAQAAAAEAAAABABgAAAAAAAQAAAATCwAAEwsAAAAAAAAAAAAAQkdScwAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAAAAAAAAAAAAAAAAAAAD///8A"""
JPG = """/9j/4AAQSkZJRgABAQEASABIAAD//gATQ3JlYXRlZCB3aXRoIEdJTVD/2wBDAP
//////////////////////////////////////////////////////////////////////////////////////2wBDAf///////
///////////////////////////////////////////////////////////////////////////////wgARCAABAAEDAREAAhEB
AxEB/8QAFAABAAAAAAAAAAAAAAAAAAAAAv/EABQBAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhADEAAAAUf/xAAUEAEAAAAAAAA
AAAAAAAAAAAAA/9oACAEBAAEFAn//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/AX//xAAUEQEAAAAAAAAAAAAAAAAAAA
AA/9oACAECAQE/AX//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAY/An//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBA
AE/IX//2gAMAwEAAgADAAAAEB//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EH//xAAUEQEAAAAAAAAAAAAAAAAAAAAA
/9oACAECAQE/EH//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EH//2Q=="""
SVG = b"""PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iaXNvLTg4NTktMSI/PjwhRE9DVFlQRSBzdmcgUFVCTElDICItLy9XM0MvL0RURCBTVkcgMjAwMDExMDIvL0VOIlxuICJodHRwOi8vd3d3LnczLm9yZy9UUi8yMDAwL0NSLVNWRy0yMDAwMTEwMi9EVEQvc3ZnLTIwMDAxMTAyLmR0ZCI+PHN2ZyB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIj48ZyB0cmFuc2Zvcm09InRyYW5zbGF0ZSg1MCw1MCkiPjxyZWN0IHg9IjAiIHk9IjAiIHdpZHRoPSIxNTAiIGhlaWdodD0iNTAiIHN0eWxlPSJmaWxsOnJlZDsiIC8+PC9nPjwvc3ZnPg=="""
NAMESPACED_SVG = b"""<svg:svg xmlns:svg="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <svg:rect x="10" y="10" width="80" height="80" fill="green" />
</svg:svg>"""

WEBP = b"""UklGRjoAAABXRUJQVlA4IC4AAAAwAQCdASoBAAEAAUAmJaAAA3AA/u/uY//8s//2W/7LeM///5Bj
/dl/pJxGAAAA"""

ZIP = b"""UEsDBBQACAAIAGFva1AAAAAAAAAAAAAAAAAFACAAdC50eHRVVA0AB5bgaF6W4GheluBoXnV4CwABBOgDAAAE6AMAAA
MAUEsHCAAAAAACAAAAAAAAAFBLAQIUAxQACAAIAGFva1AAAAAAAgAAAAAAAAAFACAAAAAAAAAAAACkgQAAAAB0LnR4dFVUDQAHlu
BoXpbgaF6W4GhedXgLAAEE6AMAAAToAwAAUEsFBgAAAAABAAEAUwAAAFUAAAAAAA=="""

XML = b"""<?xml version='1.0' encoding='utf-8'?>
<Document xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>123456Odoo S.A.893873733</MsgId>
      <CreDtTm>2018-11-21T09:47:32</CreDtTm>
      <NbOfTxs>0</NbOfTxs>
      <CtrlSum>0.0</CtrlSum>
      <InitgPty>
        <Nm>Odoo S.A.</Nm>
        <Id>
          <OrgId>
            <Othr>
              <Id>BE0477472701</Id>
              <Issr>KBO-BCE</Issr>
            </Othr>
          </OrgId>
        </Id>
      </InitgPty>
    </GrpHdr>
  </CstmrCdtTrfInitn>
</Document>
"""

TXT = b"""\
Hello world!
"""
