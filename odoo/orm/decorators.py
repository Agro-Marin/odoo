import typing
import warnings
from collections.abc import Callable, Collection, Mapping
from functools import wraps

C = typing.TypeVar("C", bound=Callable)
Decorator = Callable[[C], C]

if typing.TYPE_CHECKING:
    from ._typing import BaseModel, ValuesType


def attrsetter(attr: str, value: object) -> Decorator:

    def setter(method: C) -> C:
        setattr(method, attr, value)
        return method

    return setter


@typing.overload
def constrains(
    func: Callable[[BaseModel], Collection[str]], /, *, sudo: bool = True
) -> Decorator: ...


@typing.overload
def constrains(*args: str, sudo: bool = True) -> Decorator: ...


def constrains(*args, sudo: bool = True) -> Decorator:
    if args and callable(args[0]):
        if len(args) > 1:
            raise TypeError(
                "constrains() takes either a single callable or field-name "
                f"strings, not both (extra arguments {args[1:]!r} would be "
                "silently ignored)"
            )
        args = args[0]
    elif not all(isinstance(arg, str) for arg in args):
        raise TypeError(
            f"constrains() arguments must be field-name strings, got {args!r}"
        )

    def decorator(method: C) -> C:
        method._constrains = args
        method._constrains_sudo = sudo
        return method

    return decorator


def ondelete(*, at_uninstall: bool) -> Decorator:
    return attrsetter("_ondelete", at_uninstall)


def onchange(*args: str) -> Decorator:
    if not all(isinstance(arg, str) for arg in args):
        raise TypeError(
            f"onchange() arguments must be field-name strings, got {args!r}"
        )
    return attrsetter("_onchange", args)


def _check_depends_id(deps) -> None:
    for arg in deps:
        if "id" in arg.split("."):
            raise NotImplementedError("Compute method cannot depend on field 'id'.")


@typing.overload
def depends(func: Callable[[BaseModel], Collection[str]], /) -> Decorator: ...


@typing.overload
def depends(*args: str) -> Decorator: ...


def depends(*args) -> Decorator:
    if args and callable(args[0]):
        if len(args) > 1:
            raise TypeError(
                "depends() takes either a single callable or field-name "
                f"strings, not both (extra arguments {args[1:]!r} would be "
                "silently ignored)"
            )
        original = args[0]

        @wraps(original)
        def _depends_callable(self):
            deps = tuple(original(self))
            _check_depends_id(deps)
            return deps

        args = _depends_callable
    else:
        if not all(isinstance(arg, str) for arg in args):
            raise TypeError(
                "depends() arguments must be dot-separated field-name "
                f"strings, got {args!r}"
            )
        _check_depends_id(args)
    return attrsetter("_depends", args)


def depends_context(*args: str) -> Decorator:
    if not all(isinstance(arg, str) for arg in args):
        raise TypeError(
            f"depends_context() arguments must be context-key strings, got {args!r}"
        )
    return attrsetter("_depends_context", args)


def autovacuum[C: Callable](method: C) -> C:
    if not method.__name__.startswith("_"):
        raise TypeError(
            f"{method.__name__}: autovacuum methods must be private (start with '_')"
        )
    method._autovacuum = True
    return method


def job(
    method: Callable | None = None,
    /,
    *,
    channel: str = "root",
    priority: int = 10,
    max_retries: int = 5,
) -> Callable:

    def decorate[C: Callable](func: C) -> C:
        if not func.__name__.startswith("_"):
            raise TypeError(
                f"{func.__name__}: job methods must be private (start with '_')"
            )
        func._job_config = {
            "channel": channel,
            "priority": priority,
            "max_retries": max_retries,
        }
        return func

    if method is not None:
        return decorate(method)
    return decorate


def model[C: Callable](method: C) -> C:
    method._api_model = True
    return method


def private[C: Callable](method: C) -> C:
    method._api_private = True
    return method


def readonly[C: Callable](method: C) -> C:
    method._readonly = True
    return method


def deprecated(reason: str) -> Decorator:

    def decorator(method: C) -> C:
        @wraps(method)
        def wrapper(*args: object, **kwargs: object) -> object:
            warnings.warn(
                f"Call to deprecated method {method.__qualname__}: {reason}",
                DeprecationWarning,
                stacklevel=2,
            )
            return method(*args, **kwargs)

        wrapper.__deprecated__ = reason
        return wrapper

    return decorator


def model_create_multi[T](
    method: Callable[[T, list[ValuesType]], T],
) -> Callable[[T, list[ValuesType] | ValuesType], T]:

    @wraps(method)
    def create(self: T, vals_list: list[ValuesType] | ValuesType) -> T:
        if isinstance(vals_list, Mapping):
            vals_list = [vals_list]
        return method(self, vals_list)

    create._api_model = True
    return create
