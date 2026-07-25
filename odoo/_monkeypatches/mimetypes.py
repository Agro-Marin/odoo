import mimetypes


def patch_module() -> None:
    mimetypes.add_type("font/woff", ".woff")
    mimetypes.add_type("application/vnd.ms-fontobject", ".eot")
    mimetypes.add_type("font/ttf", ".ttf")
    mimetypes.add_type("image/webp", ".webp")
    mimetypes.add_type("image/svg+xml", ".svg")
    mimetypes.add_type("text/javascript", ".js")
