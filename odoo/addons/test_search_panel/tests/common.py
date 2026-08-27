SEARCH_PANEL_ERROR = {
    "error_msg": "Too many items to display.",
}


def strip_version(result):
    if isinstance(result, dict):
        result.pop("__version", None)
    return result
