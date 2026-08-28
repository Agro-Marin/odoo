/** @odoo-module native */
/**
 * Golden vectors for the barcode parser -- the single source of truth for both
 * runtimes.
 *
 * The parser exists twice, in Python (barcodes/models/barcode_nomenclature.py)
 * and in JS (barcodes/static/src/js/barcode_parser.js), and the two silently
 * drifted apart for years: UPC/EAN conversion worked on the client and was dead
 * on the server, "$"-anchored patterns matched trailing garbage on the server
 * only, and a barcode containing "." failed to match on the server only.
 *
 * Read by:
 *   JS     -> barcodes/static/tests/barcode_conformance.test.js
 *   Python -> barcodes/tests/test_barcode_conformance.py, which slices the
 *             template literal below and json.loads it.
 *
 * The payload is a JSON string rather than an object literal on purpose:
 * prettier rewrites an object literal into JS style (dropping the quotes around
 * keys), which is not JSON any more and broke the Python half. Inside a
 * template literal it is left alone, so one file can serve both runtimes.
 *
 * Add a case here, and a change that moves one runtime and not the other fails
 * on the side that did not move.
 */

export const VECTORS = JSON.parse(`
{
    "cases": [
        {
            "name": "ean8 rule, no numeric group",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "ean8",
                    "pattern": "........",
                    "type": "product"
                }
            ],
            "expected": [
                {
                    "barcode": "12345670",
                    "type": "product",
                    "encoding": "ean8",
                    "base_code": "12345670",
                    "value": 0
                },
                {
                    "barcode": "12345678",
                    "type": "error",
                    "encoding": "",
                    "base_code": "12345678",
                    "value": 0
                },
                {
                    "barcode": "0002",
                    "type": "error",
                    "encoding": "",
                    "base_code": "0002",
                    "value": 0
                }
            ]
        },
        {
            "name": "ean8 rule consuming the whole barcode as a value",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "ean8",
                    "pattern": "{NNNNNNNN}",
                    "type": "product"
                }
            ],
            "expected": [
                {
                    "barcode": "12345670",
                    "type": "product",
                    "encoding": "ean8",
                    "base_code": "00000000",
                    "value": 12345670
                },
                {
                    "barcode": "02003405",
                    "type": "product",
                    "encoding": "ean8",
                    "base_code": "00000000",
                    "value": 2003405
                }
            ]
        },
        {
            "name": "ean13 rule with whole and decimal parts",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "ean13",
                    "pattern": "1........{NND}.",
                    "type": "product"
                }
            ],
            "expected": [
                {
                    "barcode": "1020034051259",
                    "type": "product",
                    "encoding": "ean13",
                    "base_code": "1020034050009",
                    "value": 12.5
                }
            ]
        },
        {
            "name": "rule order follows sequence",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "ean13",
                    "pattern": "22......{NNDD}.",
                    "type": "product",
                    "sequence": 2
                },
                {
                    "encoding": "ean13",
                    "pattern": ".....{NNNDDDD}.",
                    "type": "product",
                    "sequence": 3
                }
            ],
            "expected": [
                {
                    "barcode": "2212345610259",
                    "type": "product",
                    "encoding": "ean13",
                    "base_code": "2212345600007",
                    "value": 10.25
                },
                {
                    "barcode": "2012345610255",
                    "type": "product",
                    "encoding": "ean13",
                    "base_code": "2012300000008",
                    "value": 456.1025
                }
            ]
        },
        {
            "name": "upc2ean: a UPC-A scan matches an ean13 rule",
            "nomenclature": {
                "upc_ean_conv": "always"
            },
            "rules": [
                {
                    "encoding": "ean13",
                    "pattern": ".*",
                    "type": "product"
                }
            ],
            "expected": [
                {
                    "barcode": "036000291452",
                    "type": "product",
                    "encoding": "ean13",
                    "code": "0036000291452",
                    "value": 0
                },
                {
                    "barcode": "5449000000996",
                    "type": "product",
                    "encoding": "ean13",
                    "code": "5449000000996",
                    "value": 0
                }
            ]
        },
        {
            "name": "ean2upc: a 0-prefixed EAN-13 scan matches a upca rule",
            "nomenclature": {
                "upc_ean_conv": "always"
            },
            "rules": [
                {
                    "encoding": "upca",
                    "pattern": ".*",
                    "type": "product"
                }
            ],
            "expected": [
                {
                    "barcode": "0036000291452",
                    "type": "product",
                    "encoding": "upca",
                    "code": "036000291452",
                    "value": 0
                },
                {
                    "barcode": "036000291452",
                    "type": "product",
                    "encoding": "upca",
                    "code": "036000291452",
                    "value": 0
                }
            ]
        },
        {
            "name": "upc_ean_conv is directional",
            "nomenclature": {
                "upc_ean_conv": "upc2ean"
            },
            "rules": [
                {
                    "encoding": "upca",
                    "pattern": ".*",
                    "type": "product"
                }
            ],
            "expected": [
                {
                    "barcode": "0036000291452",
                    "type": "error",
                    "encoding": "",
                    "value": 0
                }
            ]
        },
        {
            "name": "upc_ean_conv=none performs no conversion",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "ean13",
                    "pattern": ".*",
                    "type": "product"
                }
            ],
            "expected": [
                {
                    "barcode": "036000291452",
                    "type": "error",
                    "encoding": "",
                    "value": 0
                }
            ]
        },
        {
            "name": "a leading-zero EAN-13 is a UPC-A, not an EAN-13",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "ean13",
                    "pattern": ".*",
                    "type": "product"
                }
            ],
            "expected": [
                {
                    "barcode": "0036000291452",
                    "type": "error",
                    "encoding": "",
                    "value": 0
                }
            ]
        },
        {
            "name": "an anchored pattern does not match trailing garbage",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "any",
                    "pattern": "^[0-9]+$",
                    "type": "product"
                }
            ],
            "expected": [
                {
                    "barcode": "12345",
                    "type": "product",
                    "encoding": "any",
                    "base_code": "12345",
                    "value": 0
                },
                {
                    "barcode": "12345abc",
                    "type": "error",
                    "encoding": "",
                    "value": 0
                }
            ]
        },
        {
            "name": "a barcode containing regex metacharacters still matches",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "any",
                    "pattern": "...{NN}",
                    "type": "product"
                }
            ],
            "expected": [
                {
                    "barcode": "12345",
                    "type": "product",
                    "encoding": "any",
                    "base_code": "12300",
                    "value": 45
                },
                {
                    "barcode": "1.2345",
                    "type": "product",
                    "encoding": "any",
                    "base_code": "1.2005",
                    "value": 34
                }
            ]
        },
        {
            "name": "a non-digit in the numeric slot is not a match",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "any",
                    "pattern": "21{NNDDD}",
                    "type": "product"
                }
            ],
            "expected": [
                {
                    "barcode": "2112345",
                    "type": "product",
                    "encoding": "any",
                    "base_code": "2100000",
                    "value": 12.345
                },
                {
                    "barcode": "21123ab",
                    "type": "error",
                    "encoding": "",
                    "value": 0
                },
                {
                    "barcode": "21²²²²²",
                    "type": "error",
                    "encoding": "",
                    "value": 0
                },
                {
                    "barcode": "2112",
                    "type": "error",
                    "encoding": "",
                    "value": 0
                }
            ]
        },
        {
            "name": "an alias is resolved from the first rule, whatever its own sequence",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "ean8",
                    "pattern": ".*",
                    "type": "product",
                    "sequence": 1
                },
                {
                    "encoding": "any",
                    "pattern": "^AAA",
                    "type": "alias",
                    "alias": "12345670",
                    "sequence": 2
                }
            ],
            "expected": [
                {
                    "barcode": "AAA",
                    "type": "product",
                    "encoding": "ean8",
                    "code": "12345670",
                    "base_code": "12345670",
                    "value": 0
                }
            ]
        },
        {
            "name": "an alias resolving to nothing reports the aliased barcode coherently",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "any",
                    "pattern": "^AAA",
                    "type": "alias",
                    "alias": "nothing-matches-this",
                    "sequence": 1
                },
                {
                    "encoding": "ean8",
                    "pattern": ".*",
                    "type": "product",
                    "sequence": 2
                }
            ],
            "expected": [
                {
                    "barcode": "AAA",
                    "type": "error",
                    "code": "nothing-matches-this",
                    "base_code": "nothing-matches-this",
                    "value": 0
                }
            ]
        },
        {
            "name": "an alias cycle terminates",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "any",
                    "pattern": "^AAA",
                    "type": "alias",
                    "alias": "BBB",
                    "sequence": 1
                },
                {
                    "encoding": "any",
                    "pattern": "^BBB",
                    "type": "alias",
                    "alias": "AAA",
                    "sequence": 2
                }
            ],
            "expected": [
                {
                    "barcode": "AAA",
                    "type": "error",
                    "value": 0
                }
            ]
        },
        {
            "name": "alternation nested inside a group before trailing pattern",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "any",
                    "pattern": "21(a|b)3",
                    "type": "product"
                }
            ],
            "expected": [
                {
                    "barcode": "21a3",
                    "type": "product",
                    "encoding": "any",
                    "base_code": "21a3",
                    "value": 0
                },
                {
                    "barcode": "21b3",
                    "type": "product",
                    "encoding": "any",
                    "base_code": "21b3",
                    "value": 0
                }
            ]
        },
        {
            "name": "no rule matches",
            "nomenclature": {
                "upc_ean_conv": "none"
            },
            "rules": [
                {
                    "encoding": "ean8",
                    "pattern": "11.....{N}",
                    "type": "product"
                }
            ],
            "expected": [
                {
                    "barcode": "16012344",
                    "type": "error",
                    "encoding": "",
                    "base_code": "16012344",
                    "value": 0
                }
            ]
        }
    ],
    "uri_cases": [
        {
            "barcode": "urn:epc:class:lgtin : 4012345.012345.998877",
            "expected": [
                {
                    "type": "product",
                    "value": "04012345123456"
                },
                {
                    "type": "lot",
                    "value": "998877"
                }
            ]
        },
        {
            "barcode": "urn:epc:id:sgtin:9521141.012345.4711",
            "expected": [
                {
                    "type": "product",
                    "value": "09521141123454"
                },
                {
                    "type": "lot",
                    "value": "4711"
                }
            ]
        },
        {
            "barcode": "urn:epc:tag:sgtin-96 : 1.358378.0728089.620776",
            "expected": [
                {
                    "type": "product",
                    "value": "03583787280898"
                },
                {
                    "type": "lot",
                    "value": "620776"
                }
            ]
        },
        {
            "barcode": "urn:epc:id:sscc:952656789012.03456",
            "expected": [
                {
                    "type": "package",
                    "value": "095265678901234568"
                }
            ]
        },
        {
            "_why": "unrecognized identifier",
            "barcode": "urn:epc:id:giai:4012345.999887",
            "expected": []
        },
        {
            "_why": "too few data fields for sgtin",
            "barcode": "urn:epc:id:sgtin:4012345.012345",
            "expected": []
        },
        {
            "_why": "too many data fields for sgtin",
            "barcode": "urn:epc:id:sgtin:4012345.012345.99.88",
            "expected": []
        },
        {
            "_why": "too few data fields for sscc",
            "barcode": "urn:epc:id:sscc:952656789012",
            "expected": []
        },
        {
            "_why": "not five ':'-separated parts",
            "barcode": "urn:",
            "expected": []
        },
        {
            "_why": "company prefix must be digits",
            "barcode": "urn:epc:id:sscc:abcdefghijkl.03456",
            "expected": []
        }
    ]
}
`);
