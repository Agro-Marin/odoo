"""Both native extensions must declare that they need the GIL.

PyO3 0.28 inverted the meaning of saying nothing. Through 0.27 an unannotated
`#[pymodule]` declared `Py_MOD_GIL_USED` and a free-threaded interpreter
re-enabled the GIL to import it; from 0.28 an unannotated module declares
`Py_MOD_GIL_NOT_USED` and the interpreter takes it at its word. Nothing in
either crate changed when the dependency did, so both silently began telling a
free-threaded CPython it was safe to run their functions in parallel.

They are not, and `cache.rs` has said so all along: the batch lookups take
**borrowed** references out of `PyDict_GetItem` and `Py_INCREF` them a few
instructions later. Under the GIL nothing can run in between. Without it another
thread can replace the dict entry in that window and drop the last reference —
which is the pattern CPython added `PyDict_GetItemRef` to replace, and which
3.14 itself points at when `PyDict_GetItem` swallows an exception.

The decisive argument needs no memory model at all: **neither extension has ever
been executed under a free-threaded interpreter.** `freethreading.yml` scopes
itself to the pure-Python `odoo/orm/components` and `odoo/db` suites, precisely
because they need no native build. Declaring safety that has never been tested
is wrong whether or not it happens to hold.

This reads the declaration out of the built binary rather than trusting the
source, because the source did not change when the meaning did. Delete it when
the borrows are converted, a free-threaded lane exercises them, and
`gil_used = false` is a claim somebody has evidence for.
"""

import ctypes
from pathlib import Path

import odoo_lint
import odoo_rust
import pytest

#: `Py_mod_gil`, and the two values it takes. From `moduleobject.h`.
PY_MOD_GIL = 4
PY_MOD_GIL_USED = 0
PY_MOD_GIL_NOT_USED = 1

CRATES = Path(__file__).resolve().parents[2] / "crates"


class _ModuleDefBase(ctypes.Structure):
    _fields_ = [
        ("ob_base", ctypes.c_byte * (ctypes.sizeof(ctypes.c_void_p) * 2)),
        ("m_init", ctypes.c_void_p),
        ("m_index", ctypes.c_ssize_t),
        ("m_copy", ctypes.c_void_p),
    ]


class _ModuleDefSlot(ctypes.Structure):
    _fields_ = [("slot", ctypes.c_int), ("value", ctypes.c_void_p)]


class _ModuleDef(ctypes.Structure):
    _fields_ = [
        ("m_base", _ModuleDefBase),
        ("m_name", ctypes.c_char_p),
        ("m_doc", ctypes.c_char_p),
        ("m_size", ctypes.c_ssize_t),
        ("m_methods", ctypes.c_void_p),
        ("m_slots", ctypes.POINTER(_ModuleDefSlot)),
        ("m_traverse", ctypes.c_void_p),
        ("m_clear", ctypes.c_void_p),
        ("m_free", ctypes.c_void_p),
    ]


def _extension_module(package):
    """The compiled module inside the wheel's package wrapper.

    maturin ships `odoo_rust/__init__.py` doing `from .odoo_rust import *`, so
    the package itself carries no module definition — asking it for one answers
    NULL, which is indistinguishable from "declared nothing" if you do not
    notice.
    """
    import importlib

    return importlib.import_module(f"{package.__name__}.{package.__name__}")


def _gil_slot(package):
    module = _extension_module(package)
    api = ctypes.pythonapi
    api.PyModule_GetDef.restype = ctypes.POINTER(_ModuleDef)
    api.PyModule_GetDef.argtypes = [ctypes.py_object]
    definition = api.PyModule_GetDef(module)
    assert definition, f"{module.__name__} has no PyModuleDef to read"
    slots = definition.contents.m_slots
    assert slots, f"{module.__name__} declares no module slots at all"
    index = 0
    while slots[index].slot != 0:
        if slots[index].slot == PY_MOD_GIL:
            return slots[index].value or PY_MOD_GIL_USED
        index += 1
    return None


@pytest.mark.parametrize(
    "package", [odoo_rust, odoo_lint], ids=["odoo_rust", "odoo_lint"]
)
def test_the_extension_declares_that_it_needs_the_gil(package):
    slot = _gil_slot(package)
    assert slot is not None, (
        f"{package.__name__} emits no Py_mod_gil slot. On this interpreter that "
        f"means the build predates PyO3 0.28's slot, and a free-threaded one "
        f"would make its own assumption."
    )
    assert slot == PY_MOD_GIL_USED, (
        f"{package.__name__} declares Py_MOD_GIL_NOT_USED — it is telling a "
        f"free-threaded CPython that its functions are safe to run in parallel. "
        f"Neither extension has ever run under one. If this is deliberate, the "
        f"borrowed references in cache.rs have to become PyDict_GetItemRef "
        f"first and a lane has to exercise them; see this module's docstring."
    )


@pytest.mark.parametrize("crate", ["odoo_rust", "odoo_lint"])
def test_the_source_says_so_too(crate):
    """The binary is the authority; the source must not disagree with it.

    Checked separately because the two can drift in the direction that matters:
    a source that says nothing produced a binary that said NOT_USED, and the
    diff for that regression was empty.
    """
    lib = (CRATES / crate / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "#[pymodule(gil_used = true)]" in lib, (
        f"crates/{crate}/src/lib.rs does not spell `gil_used = true`. Leaving "
        f"it off does not mean 'the default is fine': PyO3 0.28 changed which "
        f"default that is, and the module began claiming free-threading safety "
        f"with no source change to review."
    )
