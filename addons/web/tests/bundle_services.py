import re
from collections.abc import Callable
from pathlib import Path

from odoo.tests import TransactionCase

_SERVICES_CATEGORY = r"""category\(\s*["']services["']\s*\)"""
_REGISTRATION = re.compile(_SERVICES_CATEGORY + r"""\s*\.add\(\s*["']([\w.-]+)["']""")
_REGISTRY_ALIAS = re.compile(
    r"(?:const|let|var)\s+(\w+)\s*=\s*registry\s*\.\s*" + _SERVICES_CATEGORY
)
_REQUIRED_SERVICE = re.compile(r"""(?<![\w.$])useService\(\s*["']([\w.-]+)["']""")
_REQUIRED_ACTION = re.compile(r"(?<![\w.$])(?<!function )useAction\(")


def registered_services(source: str) -> set[str]:
    names = set(_REGISTRATION.findall(source))
    for alias in _REGISTRY_ALIAS.findall(source):
        names.update(
            re.findall(
                rf"""(?<![\w.$]){re.escape(alias)}\s*\.add\(\s*["']([\w.-]+)["']""",
                source,
            )
        )
    return names


def required_services(source: str) -> set[str]:
    names = set(_REQUIRED_SERVICE.findall(source))
    if _REQUIRED_ACTION.search(source):
        names.add("action")
    return names


def _addon_of(url_path: str) -> tuple[str, str]:
    addon, _, rest = url_path.lstrip("/").partition("/")
    return addon, rest


def addon_sources(*addons: str) -> Callable[[str], bool]:
    def owns(url_path: str) -> bool:
        addon, rest = _addon_of(url_path)
        return rest.startswith("static/src/") and any(
            addon == name or addon.startswith(f"{name}_") for name in addons
        )

    return owns


def sources_outside(*addons: str) -> Callable[[str], bool]:
    def owns(url_path: str) -> bool:
        addon, rest = _addon_of(url_path)
        return rest.startswith("static/src/") and addon not in addons

    return owns


def bundle_scripts(env, bundle: str) -> dict[str, str]:
    IrAsset = env["ir.asset"]
    return {
        entry.path: Path(entry.full_path).read_text(encoding="utf-8")
        for entry in IrAsset._get_asset_paths(bundle, IrAsset._prepare_assets_params())
        if not entry.is_external and entry.path.endswith(".js")
    }


def unregistered_service_requirements(
    env, bundle: str, owns: Callable[[str], bool] | None = None
) -> dict[str, set[str]]:
    scripts = bundle_scripts(env, bundle)
    registered = set().union(*map(registered_services, scripts.values()))
    return {
        path: missing
        for path, source in scripts.items()
        if (owns is None or owns(path))
        and (missing := required_services(source) - registered)
    }


class BundleServicesCase(TransactionCase):
    maxDiff = None

    def assertBundleStartsRequiredServices(
        self,
        bundle: str,
        owns: Callable[[str], bool] | None = None,
        dormant: dict[str, set[str]] | None = None,
    ):
        self.assertTrue(
            bundle_scripts(self.env, bundle), f"{bundle} resolves to no script"
        )
        self.assertEqual(
            unregistered_service_requirements(self.env, bundle, owns),
            dormant or {},
            f"a component in {bundle} calls useService()/useAction() for a service that "
            "bundle never registers, so mounting it there throws 'Service <name> is not "
            "available'; take it with useOptionalService() where the bundle does without "
            "it, register the service in the bundle, or move the requirement to a subclass "
            "only the bundle that starts the service ships",
        )
