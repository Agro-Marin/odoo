import functools
import logging
import typing
from typing import Literal

from odoo.db.schema import column_exists
from odoo.tools import OrderedSet, reset_cached_properties

from .module import Manifest

if typing.TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, Mapping

    from odoo.db import BaseCursor

    STATES = Literal[
        "uninstallable",
        "uninstalled",
        "installed",
        "to upgrade",
        "to remove",
        "to install",
    ]

_logger = logging.getLogger(__name__)


class ModuleNode:
    def __init__(self, name: str, module_graph: ModuleGraph) -> None:
        self.name: str = name
        manifest = Manifest.for_addon(name, display_warning=False)
        if manifest is not None:
            manifest._force_parse()
        self.manifest: Mapping = manifest or {}

        self.id: int = 0
        self.state: STATES = "uninstalled"
        self.demo: bool = False
        self.db_version: str | None = None

        self.load_state: STATES = "uninstalled"
        self.load_version: str | None = None

        self.depends: OrderedSet[ModuleNode] = OrderedSet()
        self.module_graph: ModuleGraph = module_graph

    @functools.cached_property
    def order_name(self) -> str:
        if self.name.startswith("test_"):
            last_installed_dependency = max(
                self.depends, key=lambda m: (m.depth, m.order_name)
            )
            return last_installed_dependency.order_name + " " + self.name

        return self.name

    @functools.cached_property
    def depth(self) -> int:
        if self.name.startswith("test_"):
            last_installed_dependency = max(
                self.depends, key=lambda m: (m.depth, m.order_name)
            )
            return last_installed_dependency.depth

        return max(module.depth for module in self.depends) + 1 if self.depends else 0

    @functools.cached_property
    def phase(self) -> int:
        if self.name == "base":
            return 0

        if self.module_graph.mode == "load":
            return 1

        def not_in_the_same_phase(module: ModuleNode, dependency: ModuleNode) -> bool:
            return (module.state == "to install") ^ (dependency.state == "to install")

        return max(
            dependency.phase
            + (1 if not_in_the_same_phase(self, dependency) else 0)
            + (1 if dependency.name == "base" else 0)
            for dependency in self.depends
        )

    @property
    def demo_installable(self) -> bool:
        return all(p.demo for p in self.depends)


class ModuleGraph:
    def __init__(
        self, cr: BaseCursor, mode: Literal["load", "update"] = "load"
    ) -> None:
        self.mode: Literal["load", "update"] = mode
        self._modules: dict[str, ModuleNode] = {}
        self._cr: BaseCursor = cr

    def __contains__(self, name: str) -> bool:
        return name in self._modules

    def __getitem__(self, name: str) -> ModuleNode:
        return self._modules[name]

    def __iter__(self) -> Iterator[ModuleNode]:
        return iter(
            sorted(
                self._modules.values(),
                key=lambda p: (p.phase, p.depth, p.order_name),
            )
        )

    def __len__(self) -> int:
        return len(self._modules)

    def extend(self, names: Collection[str]) -> None:
        for module in self._modules.values():
            reset_cached_properties(module)

        names = [name for name in names if name not in self._modules]

        for name in names:
            module = self._modules[name] = ModuleNode(name, self)
            if not module.manifest.get("installable"):
                if name in self._imported_modules:
                    self._remove(name, log_dependents=False)
                else:
                    _logger.warning("module %s: not installable, skipped", name)
                    self._remove(name)

        self._update_depends(names)
        self._update_depth(names)
        self._update_from_database(names)

    @functools.cached_property
    def _imported_modules(self) -> OrderedSet[str]:
        result = ["studio_customization"]
        if column_exists(self._cr, "ir_module_module", "imported"):
            self._cr.execute("SELECT name FROM ir_module_module WHERE imported")
            result += [m[0] for m in self._cr.fetchall()]
        return OrderedSet(result)

    def _update_depends(self, names: Iterable[str]) -> None:
        for name in names:
            if module := self._modules.get(name):
                depends = module.manifest["depends"]
                try:
                    module.depends = OrderedSet(self._modules[dep] for dep in depends)
                except KeyError:
                    missing = [dep for dep in depends if dep not in self._modules]
                    _logger.warning(
                        "module %s: some depends are not loaded (%s), skipped",
                        name,
                        ", ".join(missing),
                    )
                    self._remove(name)

    def _update_depth(self, names: Iterable[str]) -> None:
        for cycle_member in self._find_cycle_members():
            if cycle_member in self._modules:
                _logger.warning(
                    "module %s: in a dependency loop, skipped",
                    cycle_member,
                )
                self._remove(cycle_member)
        for name in names:
            if module := self._modules.get(name):
                _ = module.depth

    def _find_cycle_members(self) -> set[str]:
        indices: dict[str, int] = {}
        lowlinks: dict[str, int] = {}
        on_scc_stack: set[str] = set()
        scc_stack: list[str] = []
        on_cycle: set[str] = set()
        counter = 0

        def deps_of(name: str) -> list[str]:
            return [
                d.name for d in self._modules[name].depends if d.name in self._modules
            ]

        for root in list(self._modules):
            if root in indices:
                continue
            indices[root] = lowlinks[root] = counter
            counter += 1
            scc_stack.append(root)
            on_scc_stack.add(root)
            work: list[list] = [[root, 0, deps_of(root)]]

            while work:
                name, idx, deps = work[-1]
                if idx < len(deps):
                    work[-1][1] = idx + 1
                    child = deps[idx]
                    if child not in indices:
                        indices[child] = lowlinks[child] = counter
                        counter += 1
                        scc_stack.append(child)
                        on_scc_stack.add(child)
                        work.append([child, 0, deps_of(child)])
                    elif child in on_scc_stack:
                        lowlinks[name] = min(lowlinks[name], indices[child])
                else:
                    if lowlinks[name] == indices[name]:
                        scc: list[str] = []
                        while True:
                            w = scc_stack.pop()
                            on_scc_stack.discard(w)
                            scc.append(w)
                            if w == name:
                                break
                        if len(scc) > 1 or name in deps_of(name):
                            on_cycle.update(scc)
                    work.pop()
                    if work:
                        parent = work[-1][0]
                        lowlinks[parent] = min(lowlinks[parent], lowlinks[name])

        return on_cycle

    def _update_from_database(self, names: Iterable[str]) -> None:
        names = tuple(name for name in names if name in self._modules)
        if not names:
            return
        query = """
            SELECT name, id, state, demo, db_version
            FROM ir_module_module
            WHERE name = ANY(%s)
        """
        self._cr.execute(query, [list(names)])
        for name, id_, state, demo, db_version in self._cr.fetchall():
            if name not in self._modules:
                continue
            if state == "uninstallable":
                _logger.warning("module %s: not installable, skipped", name)
                self._remove(name)
                continue
            if self.mode == "load" and state in ["to install", "uninstalled"]:
                _logger.info("module %s: not installed, skipped", name)
                self._remove(name)
                continue
            module = self._modules[name]
            module.id = id_
            module.state = state
            module.demo = demo
            module.db_version = db_version
            module.load_version = db_version
            module.load_state = state

    def _remove(self, name: str, log_dependents: bool = True) -> None:
        module = self._modules.pop(name)
        for another, another_module in list(self._modules.items()):
            if (
                module in another_module.depends
                and another_module.name in self._modules
            ):
                if log_dependents:
                    _logger.info(
                        "module %s: its direct/indirect dependency is skipped, skipped",
                        another,
                    )
                self._remove(another)
