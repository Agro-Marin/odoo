/** @odoo-module native */

// A module addressed by its DIRECTORY: there is no faced.js beside this
// directory, so `@…/native_esm/faced` only resolves if the reader falls back
// to <spec>/index.js. Outside the native_esm/*.js glob on purpose -- it is a
// resolution fixture, not a bundle member.
export const FACED = "faced";
