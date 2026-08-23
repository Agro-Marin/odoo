import base64
import binascii
import io
from random import randrange
from typing import Any, Literal, Self

# `Image.preinit()` below registers only PIL's built-in shortlist (BMP, GIF,
# JPEG, PPM, PNG) and `_initialized = 2` then tells PIL not to scan for the
# rest.  Anything else this module must open has to be imported by hand to get
# itself registered -- which is the entire reason IcoImagePlugin is here.
from PIL import (
    IcoImagePlugin,  # noqa: F401  registers the ICO plugin; see the note above
    Image,
    ImageOps,
    ImageSequence,
)
from PIL.Image import Image as PILImage
from PIL.Image import Palette, Resampling


class ImageError(ValueError):
    pass


class ImageDecodeError(ImageError):
    pass


class ImageTooLargeError(ImageError):
    pass


class NotWebpError(ImageError):
    pass


FILETYPE_BASE64_MAGICWORD = {
    b"/": "jpg",
    b"R": "gif",
    b"i": "png",
    b"P": "svg+xml",
    b"U": "webp",
}

EXIF_TAG_ORIENTATION = 0x112

IMAGE_MAX_RESOLUTION = 50e6


Image.preinit()
Image._initialized = 2


def image_fix_orientation(image: PILImage) -> PILImage:
    return ImageOps.exif_transpose(image)


def image_apply_opt(image: PILImage, output_format: str, **params) -> bytes:
    if output_format == "JPEG" and image.mode not in ["1", "L", "RGB"]:
        image = image.convert("RGB")
    stream = io.BytesIO()
    image.save(stream, format=output_format, **params)
    return stream.getvalue()


def image_to_base64(image: PILImage, output_format: str, **params) -> bytes:
    stream = image_apply_opt(image, output_format, **params)
    return base64.b64encode(stream)


def image_data_uri(base64_source: bytes) -> str:
    filetype = FILETYPE_BASE64_MAGICWORD.get(base64_source[:1], "png")
    return f"data:image/{filetype};base64,{base64_source.decode()}"


class ImageProcess:
    image: PILImage | Literal[False]
    source: bytes | Literal[False]
    original_format: str

    def __init__(
        self, source: bytes | Literal[False] | None, verify_resolution: bool = True
    ) -> None:
        self.source = source or False
        self.operations_count = 0
        self.original_format = ""
        self.animated_frames: list[PILImage] = []

        if not source or source[:1] == b"<":
            self.image = False
        elif source[0:4] == b"RIFF" and source[8:15] == b"WEBPVP8":
            self.image = False
            if verify_resolution:
                size = get_webp_size(source)
                if size and size[0] * size[1] > IMAGE_MAX_RESOLUTION:
                    raise ImageTooLargeError(
                        f"Too large image (above {IMAGE_MAX_RESOLUTION / 1e6}Mpx), reduce the image size."
                    )
        else:
            self.image = binary_to_image(source)

            w, h = self.image.size
            if verify_resolution and w * h > IMAGE_MAX_RESOLUTION:
                raise ImageTooLargeError(
                    f"Too large image (above {IMAGE_MAX_RESOLUTION / 1e6}Mpx), reduce the image size."
                )

            self.original_format = (self.image.format or "").upper()

            if self.original_format != "GIF":
                # exif_transpose returns a fresh single-frame image, which
                # would drop every frame after the first. GIF carries no EXIF
                # orientation tag, so there is nothing to correct anyway.
                self.image = image_fix_orientation(self.image)

    def _extract_gif_frames(self) -> None:
        """Detach the frames from the read-only GIF stream, once.

        A ``GifImageFile`` seeks within its source, so operations on it do not
        stick and ``self.image.size`` never changes. Copying the frames out
        makes ``self.image`` an ordinary image that resizes and crops normally,
        with the rest of the animation carried in ``animated_frames``.
        """
        if self.original_format == "GIF" and not self.animated_frames:
            frames = [frame.copy() for frame in ImageSequence.Iterator(self.image)]
            if frames:
                self.image = frames[0]
                self.animated_frames = frames[1:]

    def image_quality(
        self, quality: int = 0, output_format: str = ""
    ) -> bytes | Literal[False]:
        if not self.image:
            return self.source

        source = self.source
        assert source is not False, "an image was decoded from a falsy source"

        output_image = self.image

        output_format = output_format.upper() or self.original_format
        if output_format == "BMP":
            output_format = "PNG"
        elif output_format not in ["PNG", "JPEG", "GIF", "ICO"]:
            output_format = "JPEG"

        if (
            not self.operations_count
            and output_format == self.original_format
            and not quality
        ):
            return self.source

        opt: dict[str, Any] = {"output_format": output_format}

        if output_format == "PNG":
            opt["optimize"] = True
            if quality:
                if output_image.mode != "P":
                    output_image = output_image.convert("RGBA").convert(
                        "P", palette=Palette.WEB, colors=256
                    )
        if output_format == "JPEG":
            opt["optimize"] = True
            opt["quality"] = quality or 95
        if output_format == "GIF":
            opt["optimize"] = True
            opt["save_all"] = True
            opt["append_images"] = self.animated_frames

        if output_image.mode not in ["1", "L", "P", "RGB", "RGBA"] or (
            output_format == "JPEG" and output_image.mode == "RGBA"
        ):
            output_image = output_image.convert("RGB")

        output_bytes = image_apply_opt(output_image, **opt)
        if (
            len(output_bytes) >= len(source)
            and self.original_format == output_format
            and not self.operations_count
        ):
            return source
        return output_bytes

    def resize(
        self, max_width: int = 0, max_height: int = 0, expand: bool = False
    ) -> Self:
        if self.image and (max_width or max_height):
            w, h = self.image.size
            asked_width = max_width or (w * max_height) // h
            asked_height = max_height or (h * max_width) // w
            if self.original_format == "GIF":
                if asked_width < w or asked_height < h:
                    self._extract_gif_frames()
                    for frame in [self.image, *self.animated_frames]:
                        frame.thumbnail(
                            (asked_width, asked_height), Resampling.LANCZOS
                        )
                    self.operations_count += 1
                return self
            if expand and (asked_width > w or asked_height > h):
                self.image = self.image.resize((asked_width, asked_height))
                self.operations_count += 1
                return self
            if asked_width != w or asked_height != h:
                self.image.thumbnail((asked_width, asked_height), Resampling.LANCZOS)
                if self.image.width != w or self.image.height != h:
                    self.operations_count += 1
        return self

    def crop_resize(
        self,
        max_width: int,
        max_height: int,
        center_x: float = 0.5,
        center_y: float = 0.5,
    ) -> Self:
        if self.image and max_width and max_height:
            w, h = self.image.size
            if w / max_width > h / max_height:
                new_w, new_h = w, (max_height * w) // max_width
            else:
                new_w, new_h = (max_width * h) // max_height, h

            if new_w > w:
                new_w, new_h = w, (new_h * w) // new_w
            if new_h > h:
                new_w, new_h = (new_w * h) // new_h, h

            new_w, new_h = max(new_w, 1), max(new_h, 1)

            x_offset = int((w - new_w) * center_x)
            h_offset = int((h - new_h) * center_y)

            if new_w != w or new_h != h:
                crop_box = (x_offset, h_offset, x_offset + new_w, h_offset + new_h)
                if self.original_format == "GIF":
                    self._extract_gif_frames()
                    self.image = self.image.crop(crop_box)
                    self.animated_frames = [
                        frame.crop(crop_box) for frame in self.animated_frames
                    ]
                    self.operations_count += 1
                else:
                    self.image = self.image.crop(crop_box)
                    if self.image.width != w or self.image.height != h:
                        self.operations_count += 1

        return self.resize(max_width, max_height)

    def colorize(self, color: tuple[int, int, int] | None = None) -> Self:
        if color is None:
            color = (
                randrange(32, 224, 24),
                randrange(32, 224, 24),
                randrange(32, 224, 24),
            )
        if self.image:
            original = self.image
            if original.mode == "P":
                # A palette image carries its transparency in `info`, not in a
                # band, so it has no usable mask until it is expanded.
                original = original.convert("RGBA")
            self.image = Image.new("RGB", original.size)
            self.image.paste(color, box=(0, 0) + original.size)
            # The original doubles as the paste mask so that transparent pixels
            # keep the fill.  PIL accepts a mask only in "1"/"L"/"LA"/"RGBA";
            # an RGB source -- the commonest mode there is -- used to raise
            # "ValueError: bad transparency mask" here.  With nothing to see
            # through, the fill is simply covered.
            mask = original if original.mode in ("1", "L", "LA", "RGBA") else None
            self.image.paste(original, mask=mask)
            self.operations_count += 1
        return self

    def add_padding(self, padding: int) -> Self:
        if self.image:
            img_width, img_height = self.image.size
            if 2 * padding >= min(img_width, img_height):
                raise ValueError(
                    f"padding {padding} is too large for a "
                    f"{img_width}x{img_height} image"
                )
            self.image = self.image.resize(
                (img_width - 2 * padding, img_height - 2 * padding)
            )
            self.image = ImageOps.expand(self.image, border=padding)
            self.operations_count += 1
        return self


def image_process(
    source: bytes | Literal[False] | None,
    size: tuple[int, int] = (0, 0),
    verify_resolution: bool = False,
    quality: int = 0,
    expand: bool = False,
    crop: str | None = None,
    colorize: bool | tuple[int, int, int] = False,
    output_format: str = "",
    padding: int | bool = False,
    processor: type[ImageProcess] = ImageProcess,
) -> bytes | Literal[False] | None:
    if not source or (
        (not size or (not size[0] and not size[1]))
        and not verify_resolution
        and not quality
        and not crop
        and not colorize
        and not output_format
        and not padding
    ):
        return source

    image = processor(source, verify_resolution)
    if size:
        if crop:
            center_x = 0.5
            center_y = 0.5
            if crop == "top":
                center_y = 0
            elif crop == "bottom":
                center_y = 1
            image.crop_resize(
                max_width=size[0],
                max_height=size[1],
                center_x=center_x,
                center_y=center_y,
            )
        else:
            image.resize(max_width=size[0], max_height=size[1], expand=expand)
    if padding:
        image.add_padding(padding)
    if colorize:
        image.colorize(colorize if isinstance(colorize, tuple) else None)
    return image.image_quality(quality=quality, output_format=output_format)


def average_dominant_color(
    colors: list[tuple[int, tuple[int, int, int, int]]],
    mitigate: int = 175,
    max_margin: int = 140,
) -> tuple[tuple[int, int, int], list[tuple[int, tuple[int, int, int, int]]]]:
    if not colors:
        msg = "colors must be a non-empty list of (count, (r, g, b, a)) tuples"
        raise ValueError(msg)
    total_count = sum(col[0] for col in colors)
    if not total_count:
        msg = "colors must contain at least one entry with a non-zero count"
        raise ValueError(msg)

    dominant_color = max(colors)
    dominant_rgb = dominant_color[1][:3]
    dominant_set = [dominant_color]
    remaining = []

    margins = [max_margin * (1 - dominant_color[0] / total_count)] * 3

    colors = [c for c in colors if c is not dominant_color]

    for color in colors:
        rgb = color[1]
        if (
            rgb[0] < dominant_rgb[0] + margins[0]
            and rgb[0] > dominant_rgb[0] - margins[0]
            and rgb[1] < dominant_rgb[1] + margins[1]
            and rgb[1] > dominant_rgb[1] - margins[1]
            and rgb[2] < dominant_rgb[2] + margins[2]
            and rgb[2] > dominant_rgb[2] - margins[2]
        ):
            dominant_set.append(color)
        else:
            remaining.append(color)

    dominant_avg = []
    for band in range(3):
        avg = total = 0
        for color in dominant_set:
            avg += color[0] * color[1][band]
            total += color[0]
        dominant_avg.append(int(avg / total))

    final_dominant = []
    brightest = max(dominant_avg)
    for band in range(3):
        value = (
            dominant_avg[band] / (brightest / mitigate)
            if brightest > mitigate
            else dominant_avg[band]
        )
        final_dominant.append(int(value))

    red, green, blue = final_dominant
    return (red, green, blue), remaining


def binary_to_image(source: bytes) -> PILImage:
    try:
        return Image.open(io.BytesIO(source))
    except OSError, binascii.Error:
        msg = "This file could not be decoded as an image file."
        raise ImageDecodeError(msg) from None


def base64_to_image(base64_source: str | bytes) -> PILImage:
    # The decode stays inside the try: b64decode raises binascii.Error on
    # malformed input, and that is the same failure to the caller.
    try:
        return binary_to_image(base64.b64decode(base64_source))
    except binascii.Error:
        msg = "This file could not be decoded as an image file."
        raise ImageDecodeError(msg) from None


def get_webp_size(source: bytes) -> tuple[int, int] | None:
    if len(source) < 16 or not (source[0:4] == b"RIFF" and source[8:15] == b"WEBPVP8"):
        msg = "This file is not a webp file."
        raise NotWebpError(msg)

    vp8_type = source[15]
    if vp8_type == 0x20 and len(source) >= 30:
        width_low, width_high, height_low, height_high = source[26:30]
        width = (width_high << 8) + width_low
        height = (height_high << 8) + height_low
        return (width, height)
    elif vp8_type == 0x58 and len(source) >= 30:
        (
            width_low,
            width_medium,
            width_high,
            height_low,
            height_medium,
            height_high,
        ) = source[24:30]
        width = 1 + (width_high << 16) + (width_medium << 8) + width_low
        height = 1 + (height_high << 16) + (height_medium << 8) + height_low
        return (width, height)
    elif vp8_type == 0x4C and len(source) >= 25 and source[20] == 0x2F:
        ab, cd, ef, gh = source[21:25]
        width = 1 + ((cd & 0x3F) << 8) + ab
        height = 1 + ((gh & 0xF) << 10) + (ef << 2) + (cd >> 6)
        return (width, height)
    return None


def _decoded_image_size(base64_source: bytes | str) -> tuple[int, int] | None:
    """Width and height of a base64 image, without decoding a webp."""
    source = base64.b64decode(base64_source)
    if source[0:4] == b"RIFF" and source[8:15] == b"WEBPVP8":
        return get_webp_size(source)
    image = image_fix_orientation(binary_to_image(source))
    return image.width, image.height


def is_image_size_above(
    base64_source_1: bytes | str | None, base64_source_2: bytes | str | None
) -> bool:
    if not base64_source_1 or not base64_source_2:
        return False
    if base64_source_1[:1] in (b"P", "P") or base64_source_2[:1] in (b"P", "P"):
        return False

    source = _decoded_image_size(base64_source_1)
    target = _decoded_image_size(base64_source_2)
    if source is None or target is None:
        return False
    return source[0] > target[0] or source[1] > target[1]


def image_guess_size_from_field_name(field_name: str) -> tuple[int, int]:
    if field_name == "image":
        return (1024, 1024)
    if field_name.startswith("x_"):
        return (0, 0)
    try:
        suffix = int(field_name.rsplit("_", 1)[-1])
    except ValueError:
        return 0, 0

    if suffix < 16:
        return (0, 0)

    return (suffix, suffix)
