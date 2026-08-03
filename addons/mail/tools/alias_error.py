from dataclasses import dataclass, field


@dataclass(frozen=True)
class AliasError:
    """Alias error description.

    :param str code: error code
    :param str message: translated user message
    :param bool is_config_error: whether a mis-configured alias caused the error
    """

    code: str
    message: str = field(default="", compare=False)
    is_config_error: bool = field(default=False, compare=False)
