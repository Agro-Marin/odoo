import { expect, test } from "@odoo/hoot";
// Importing the concrete classes forces the factory invocations in those modules to
// run at load time — a broken factory application would fail this file's import.
import { SaleFileUploadKanbanRenderer } from "@sale/views/sale_file_upload_kanban/sale_file_upload_kanban_renderer";
import { SaleFileUploadListRenderer } from "@sale/views/sale_file_upload_list/sale_file_upload_list_renderer";
import {
    saleFileUploadController,
    saleFileUploadRenderer,
    saleOnboardingRenderer,
} from "@sale/views/sale_file_upload_mixins";
import { SaleKanbanRenderer } from "@sale/views/sale_onboarding_kanban/sale_onboarding_kanban_renderer";
import { SaleListRenderer } from "@sale/views/sale_onboarding_list/sale_onboarding_list_renderer";

test("saleFileUploadController hides the upload button and calls super.setup", () => {
    let superCalled = false;
    class Base {
        setup() {
            superCalled = true;
        }
    }
    const instance = new (saleFileUploadController(Base))();
    instance.setup();
    expect(superCalled).toBe(true);
    expect(instance.hideUploadButton).toBe(true);
});

test("saleFileUploadRenderer sets the RFQ drop-zone title and description", () => {
    class Base {
        setup() {}
    }
    const instance = new (saleFileUploadRenderer(Base))();
    instance.setup();
    expect(instance.dropZoneTitle).toBe(
        "Import a request for quotation from a customer",
    );
    expect(instance.dropZoneDescription.includes("UBL-RequestForQuotation")).toBe(true);
});

test("saleOnboardingRenderer adds the action helper and sets the template", () => {
    class Foo {}
    class Base {
        static components = { Foo };
    }
    const Onboarding = saleOnboardingRenderer(Base, "sale.SomeTemplate");
    expect(Onboarding.template).toBe("sale.SomeTemplate");
    // The onboarding action helper is added...
    expect(!!Onboarding.components.SaleActionHelper).toBe(true);
    // ...without dropping the base's components.
    expect(Onboarding.components.Foo).toBe(Foo);
});

test("concrete file-upload/onboarding view classes are produced correctly", () => {
    // File-upload renderers are classes (produced by the renderer factory).
    expect(typeof SaleFileUploadKanbanRenderer).toBe("function");
    expect(typeof SaleFileUploadListRenderer).toBe("function");
    // Onboarding renderers carry the template + action helper, extending the
    // file-upload renderers.
    expect(SaleKanbanRenderer.template).toBe("sale.SaleKanbanRenderer");
    expect(SaleListRenderer.template).toBe("sale.SaleListRenderer");
    expect(!!SaleKanbanRenderer.components.SaleActionHelper).toBe(true);
    expect(!!SaleListRenderer.components.SaleActionHelper).toBe(true);
    expect(SaleKanbanRenderer.prototype instanceof SaleFileUploadKanbanRenderer).toBe(
        true,
    );
    expect(SaleListRenderer.prototype instanceof SaleFileUploadListRenderer).toBe(true);
});
