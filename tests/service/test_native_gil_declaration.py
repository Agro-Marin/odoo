import ctypes
from pathlib import Path

import odoo_lint
import odoo_rust
import pytest

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
    lib = (CRATES / crate / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "#[pymodule(gil_used = true)]" in lib, (
        f"crates/{crate}/src/lib.rs does not spell `gil_used = true`. Leaving "
        f"it off does not mean 'the default is fine': PyO3 0.28 changed which "
        f"default that is, and the module began claiming free-threading safety "
        f"with no source change to review."
    )
