// @ts-check

import { expect, test } from "@odoo/hoot";
import { KanbanCompiler } from "@web/views/kanban/kanban_compiler";

function compileTemplate(arch) {
    const parser = new DOMParser();
    const xml = parser.parseFromString(arch, "text/xml");
    const compiler = new KanbanCompiler({ kanban: xml.documentElement });
    return compiler.compile("kanban");
}

test("literal ${...} in a field attribute is escaped, not interpolated", async () => {
    // Regression: the field-attribute value must be wrapped as a plain string.
    // A raw ``${expr}`` in the arch must land in the generated ``attrs`` props
    // as an escaped ``\\${...}`` (a literal template-literal sequence), never as
    // live interpolation that would evaluate ``expr`` in component scope.
    const arch = `
        <kanban>
            <templates>
                <t t-name="card">
                    <field name="foo" widget="char" placeholder="Cost \${__comp__.hacked}"/>
                </t>
            </templates>
        </kanban>`;
    const compiled = compileTemplate(arch).outerHTML;
    // The dollar sign is neutralised (``\\${``) so the generated template literal
    // renders the text verbatim instead of evaluating the interpolation.
    expect(compiled).toInclude("\\${__comp__.hacked}");
    expect(compiled).not.toInclude("`Cost ${__comp__.hacked}`");
});

test("bootstrap dropdowns with kanban_ignore_dropdown class should be left as is", async () => {
    const arch = `
        <kanban>
            <templates>
                <t t-name="card">
                    <button name="dropdown" class="kanban_ignore_dropdown" type="button" data-bs-toggle="dropdown">Boostrap dropdown</button>
                    <div class="dropdown-menu kanban_ignore_dropdown" role="menu">
                        <span>Dropdown content</span>
                    </div>
                </t>
            </templates>
        </kanban>`;
    const expected = `
        <t t-translation="off">
            <kanban>
                <templates>
                    <t t-name="card">
                        <button name="dropdown" class="kanban_ignore_dropdown" type="button" data-bs-toggle="dropdown">Boostrap dropdown</button>
                        <div class="dropdown-menu kanban_ignore_dropdown" role="menu">
                            <span>Dropdown content</span>
                        </div>
                    </t>
                </templates>
            </kanban>
        </t>`;
    expect(compileTemplate(arch)).toHaveOuterHTML(expected);
});
