import { expect, test } from "@odoo/hoot";
import { UploadButton } from "@product/js/product_document_kanban/upload_button/upload_button";
import { ProductNameAndDescriptionField } from "@product/product_name_and_description/product_name_and_description";

// ---------------------------------------------------------------------------
// UploadButton.validFileType
// ---------------------------------------------------------------------------

/** @param {string} allowed @param {string} type */
function accepts(allowed, type) {
    return UploadButton.prototype.validFileType.call(
        { props: { allowedMIMETypes: allowed }, notification: { add() {} } },
        { type, name: "probe" },
    );
}

test("a type absent from the whitelist is rejected", () => {
    expect(accepts("image/png,image/jpeg", "application/x-msdownload")).toBe(false);
});

test("a file the browser could not type is rejected", () => {
    // "" is what a browser reports for an extension it does not recognise --
    // the exact case a MIME whitelist exists to catch.
    expect(accepts("image/png,image/jpeg", "")).toBe(false);
});

test("a type that is merely a substring of the whitelist is rejected", () => {
    expect(accepts("application/pdf", "application/pd")).toBe(false);
});

test("a whitelisted type is accepted, spacing included", () => {
    expect(accepts("image/png, image/jpeg", "image/jpeg")).toBe(true);
});

test("an accept-style wildcard is honoured", () => {
    expect(accepts("image/*", "image/webp")).toBe(true);
    expect(accepts("image/*", "application/pdf")).toBe(false);
});

test("no whitelist allows everything", () => {
    expect(accepts("", "application/x-msdownload")).toBe(true);
});

// ---------------------------------------------------------------------------
// ProductNameAndDescriptionField.label
// ---------------------------------------------------------------------------

/** @param {string} productName @param {string} description */
function labelOf(productName, description) {
    const self = Object.create(ProductNameAndDescriptionField.prototype);
    Object.assign(self, {
        descriptionColumn: "name",
        props: {
            name: "product_id",
            record: {
                data: { name: description, product_id: { display_name: productName } },
            },
        },
    });
    return self.label;
}

test("the product name written as a prefix is stripped", () => {
    expect(labelOf("Desk", "Desk\nwith drawers")).toBe("with drawers");
    expect(labelOf("[DESK01] Desk", "[DESK01] Desk\nwith drawers")).toBe(
        "with drawers",
    );
});

test("a description that only mentions the product name is left alone", () => {
    // Reachable from any import or API caller: account.move.line.name is an
    // editable stored compute, so an explicit write without the prefix is kept.
    expect(labelOf("Desk", "Spare leg for a Desk")).toBe("Spare leg for a Desk");
});

test("a description equal to the product name yields no label", () => {
    expect(labelOf("Desk", "Desk")).toBe("");
});

test("an empty description does not throw", () => {
    expect(labelOf("Desk", "")).toBe("");
});
