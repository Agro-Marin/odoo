import { ResCountry } from "@point_of_sale/../tests/unit/data/res_country.data";

export const applyFrCertResCountryRecords = () => {
    ResCountry._records = [
        ...ResCountry._records,
        {
            id: 75,
            name: "France",
            code: "FR",
            vat_label: "VAT",
        },
    ];
};
