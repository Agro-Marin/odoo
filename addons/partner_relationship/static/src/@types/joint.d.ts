/**
 * Ambient type declarations for JointJS.
 *
 * The library is vendored at `addons/web/static/lib/joint/joint.esm.js` and
 * resolved at runtime through the import map `addons/web/__manifest__.py`
 * declares for the bare specifier `"joint"`. That directory is in tsconfig's
 * `exclude` list, as every vendored bundle is, so `tsc` cannot follow the
 * specifier to a source and `import("joint")` reports TS2307.
 *
 * This is the shape `addons/spreadsheet/static/src/@types/o-spreadsheet.d.ts`
 * documents for its own excluded bundle, and it is preferred to a `paths` entry
 * for the same reason: a `paths` entry would have to point INTO the excluded
 * directory, which defeats the exclusion rather than working with it.
 *
 * The declaration covers the surface `partner_relationship` actually consumes --
 * `dia` and `shapes`, destructured from the resolved module in
 * `partner_network_widget.js` -- rather than modelling JointJS. A consumer that
 * reaches for more widens this file, which is the point of having it: the next
 * member used is a one-line edit here instead of a second TS2307.
 */
declare module "joint" {
    export const dia: any;
    export const shapes: any;
    export const util: any;
    export const g: any;
}
