/**
 * ESM re-export shim for Bootstrap.
 *
 * The bundled UMD ``bootstrap.bundle.js`` sets ``globalThis.bootstrap``
 * as a single namespace containing all components.  This module
 * re-exports them as named ESM exports so native modules can do:
 *
 *     import { Tooltip, Modal } from "bootstrap";
 *
 * Same pattern as ``owl/owl_esm.js``.
 */
const _bs = globalThis.bootstrap;

export const Alert = _bs.Alert;
export const Button = _bs.Button;
export const Carousel = _bs.Carousel;
export const Collapse = _bs.Collapse;
export const Dropdown = _bs.Dropdown;
export const Modal = _bs.Modal;
export const Offcanvas = _bs.Offcanvas;
export const Popover = _bs.Popover;
export const ScrollSpy = _bs.ScrollSpy;
export const Tab = _bs.Tab;
export const Toast = _bs.Toast;
export const Tooltip = _bs.Tooltip;
export default _bs;
