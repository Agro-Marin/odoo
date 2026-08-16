from dataclasses import dataclass, field


@dataclass(frozen=True)
class AliasError:
    code: str
    message: str = field(default="", compare=False)
    is_config_error: bool = field(default=False, compare=False)
