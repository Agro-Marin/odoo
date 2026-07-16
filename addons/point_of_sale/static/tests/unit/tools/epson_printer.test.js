import { expect, test } from "@odoo/hoot";
import { EpsonPrinter } from "@point_of_sale/app/utils/printer/epson_printer";

test("epson raster rows are byte-aligned for non-multiple-of-8 widths", async () => {
    const printer = new EpsonPrinter({ ip: "192.0.2.1" });
    const canvas = document.createElement("canvas");
    canvas.width = 10;
    canvas.height = 2;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#000000";
    ctx.fillRect(0, 0, 10, 2);

    // The ePOS <image> format expects ceil(width/8) bytes per row: a 10px-wide
    // all-black canvas must yield rows of 10 ink bits + 6 padding bits. The
    // unpadded encoding produced diagonally-sheared prints.
    const raster = printer.canvasToRaster(canvas);
    expect(raster.length).toBe(32);
    expect(raster.slice(0, 16)).toBe("1111111111000000");
    expect(raster.slice(16)).toBe("1111111111000000");

    const encoded = atob(printer.encodeRaster(raster));
    expect(encoded.length).toBe(4);
    expect(encoded.charCodeAt(0)).toBe(0xff);
    expect(encoded.charCodeAt(1)).toBe(0b11000000);
    expect(encoded.charCodeAt(2)).toBe(0xff);
    expect(encoded.charCodeAt(3)).toBe(0b11000000);
});
