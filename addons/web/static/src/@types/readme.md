The types folder is a way to get better autocompletion for iife imported libs.
It uses typescript declarations to inform the IDE about some global vars and their types and methods.

These files are loaded as **ordinary program files** by the `include` glob in the
root `tsconfig.json` / `jsconfig.json` (`**/*.ts` matches `.d.ts`), and their
global declarations then apply program-wide. They are *not* `@types` packages, so
do **not** add a `typeRoots` entry pointing here: `typeRoots` resolves
`<root>/<pkg>/index.d.ts`, and nothing in this folder provides one, so such an
entry is inert. Both configs deliberately set `"types": []` instead — see the
comment there.

Adding new libs to this can be trivial or not.
It can be a one liner or the addition of a complete typescript declaration file.
It should be handled by someone that knows what they are doing.

Note that if odoo adds methods to a lib, manual additions must likely will be required to get full automcompletion.
Just like the qunit lib.
