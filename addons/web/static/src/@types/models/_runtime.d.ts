/**
 * Brand types for generated model declarations.
 *
 * The codegen script ``addons/odoo/addons/web/tooling/scripts/generate_model_types.py``
 * emits one ``.d.ts`` per Odoo model under this directory.  Each generated
 * file declares an interface using the brands below — ``Many2one<"res.partner">``
 * etc. — so that field-level types carry their related model name as a
 * string-literal type parameter.  This enables type-level dispatch in
 * downstream APIs:
 *
 *   const data: Models["sale.order"] = ...;
 *   data.partner_id;          // Many2one<"res.partner">
 *   record.fetch("partner_id"); // returns Models["res.partner"]
 *
 * The runtime values are unchanged — these are *purely type-level* tags.
 * At the wire (JSON-RPC) level a Many2one is still ``[number, string] | false``;
 * at the data-layer (RelationalRecord) level, the ``data`` getter resolves
 * a Many2one into the same tuple.  The brand just carries the model name
 * forward so static analysis can navigate the relation graph.
 *
 * Why a separate ``_runtime.d.ts`` (not co-located with the codegen output):
 * the brand definitions are hand-written and stable; the per-model files
 * are regenerated from server fields_get on every model change.  Keeping
 * them apart means model regeneration never accidentally clobbers the
 * core vocabulary.
 */

declare module "@web/@types/models/_runtime" {
    /**
     * Tagged tuple for many2one fields.  The wire/data shape is
     * ``[id, display_name] | false``; the ``__model`` phantom field
     * exists only at compile time so consumers can recover the related
     * model name (``Many2one<"res.partner">``) without losing the
     * runtime payload shape.
     *
     * @template TModel string-literal model name (e.g. ``"res.partner"``)
     */
    export type Many2one<TModel extends string> =
        | (readonly [number, string] & { readonly __model?: TModel })
        | false;

    /**
     * Tagged number-array for one2many fields.  The wire shape is
     * ``number[]`` (just IDs).  The data-layer side (StaticList) wraps
     * these into typed sub-records — see the ``records`` accessor on
     * ``RelationalRecord.data.<x2many>`` once it is generic-typed.
     *
     * @template TModel string-literal model name of the related side
     */
    export type One2many<TModel extends string> =
        readonly number[] & { readonly __model?: TModel };

    /**
     * Tagged number-array for many2many fields.  Same shape as
     * ``One2many`` at the wire level; the brand differs so consumers
     * can distinguish them statically (e.g. for default-value rules,
     * SET vs LINK semantics on save).
     *
     * @template TModel string-literal model name of the related side
     */
    export type Many2many<TModel extends string> =
        readonly number[] & { readonly __model?: TModel };

    /**
     * Reference field — string of the form ``"<model>,<id>"`` or
     * ``false``.  The codegen does not type-tag references with a
     * specific model since the model name is dynamic at runtime
     * (chosen from a configurable selection).
     */
    export type Reference = string | false;

    /**
     * Selection field — codegen emits a string-literal union of the
     * selection keys.  This alias exists so consumers can refer to
     * "the type of selection-style fields" generically; the actual
     * generated types are inline unions.
     */
    export type Selection<TKeys extends string> = TKeys;

    /**
     * Properties field — keys are user-defined per parent record, so
     * the static shape is open.  The properties widget is responsible
     * for supplying typed access via its definition lookup.
     */
    export type Properties = Record<string, unknown>;
}

/**
 * Top-level model registry.  Each generated ``.d.ts`` extends this
 * interface via declaration merging:
 *
 *   declare module "@web/@types/models/_runtime" {
 *       interface Models {
 *           "sale.order": SaleOrder;
 *       }
 *   }
 *
 * After all module-specific files merge, ``Models`` carries the union
 * of every model the fork defines.  Downstream APIs key into it:
 *
 *   class RelationalRecord<TModel extends keyof Models = string> {
 *       declare data: Models[TModel];
 *   }
 *
 * The default ``string`` makes existing untyped sites keep compiling;
 * call sites opt into typing per-call by parameterizing.
 */
declare module "@web/@types/models/_runtime" {
    export interface Models {
        // Populated via declaration merging by per-model generated files.
        // Empty here so untyped access (``Models[string]``) resolves to
        // ``unknown`` rather than ``never``.
        [model: string]: Record<string, unknown>;
    }
}
