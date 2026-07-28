// @ts-check
/** @odoo-module native */

/** @module @web/fields/parse_error - Marker base class distinguishing rejected user input from parser defects */

/**
 * Base class for "the user typed something this field cannot accept".
 *
 * Field widgets parse raw input inside a ``try``/``catch`` and flag the field
 * invalid when parsing fails. Without a marker, that ``catch`` also absorbs
 * genuine defects — a ``TypeError`` from a parser reading a property of
 * ``undefined`` is indistinguishable from a user typing "abc" into a float,
 * and disappears with no console trace.
 *
 * Parsers therefore raise a ``ParseError`` subclass for rejected input, and
 * only for rejected input. Anything else reaching the same ``catch`` is a bug
 * and is reported rather than silently swallowed (see
 * ``@web/fields/input_field_hook``).
 *
 * Kept in its own module so the generic input hook can depend on the
 * *contract* without importing the numeric parsers.
 */
export class ParseError extends Error {}
