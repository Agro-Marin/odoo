from __future__ import annotations

__all__ = [
    "ANY",
    "BARCODES",
    "CHEAP",
    "CHILDREN",
    "CUES",
    "DATA",
    "EXPENSIVE",
    "FREE",
    "IMAGES",
    "REPRESENTATIONS",
    "ROWS",
    "TEXT",
    "TREE",
]

ROWS = "rows"
TEXT = "text"
TREE = "tree"
DATA = "data"
IMAGES = "images"
BARCODES = "barcodes"
CHILDREN = "children"
CUES = "cues"

REPRESENTATIONS = (ROWS, TEXT, TREE, DATA, IMAGES, BARCODES, CHILDREN, CUES)

ANY = "*"

FREE = 0
CHEAP = 10
EXPENSIVE = 20
