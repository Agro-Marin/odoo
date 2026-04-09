/**
 * Set individual Bootstrap component globals from the bundled namespace.
 *
 * The bundled UMD (``bootstrap.bundle.js``) sets
 * ``globalThis.bootstrap = { Alert, Tooltip, ... }``.  Legacy code and
 * the ``libs/bootstrap.js`` wrapper expect individual globals
 * (``Tooltip``, ``Modal``, ``Dropdown``, etc.).  This script
 * destructures the namespace to provide them.
 *
 * Must run AFTER ``bootstrap.bundle.js`` and BEFORE any code that
 * reads the individual globals.
 */
(function () {
    "use strict";
    const bs = globalThis.bootstrap;
    if (!bs) {
        return;
    }
    globalThis.Alert = bs.Alert;
    globalThis.Button = bs.Button;
    globalThis.Carousel = bs.Carousel;
    globalThis.Collapse = bs.Collapse;
    globalThis.Dropdown = bs.Dropdown;
    globalThis.Modal = bs.Modal;
    globalThis.Offcanvas = bs.Offcanvas;
    globalThis.Popover = bs.Popover;
    globalThis.ScrollSpy = bs.ScrollSpy;
    globalThis.Tab = bs.Tab;
    globalThis.Toast = bs.Toast;
    globalThis.Tooltip = bs.Tooltip;
})();
