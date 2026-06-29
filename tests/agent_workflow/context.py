from __future__ import annotations
# ruff: noqa: F403, F405, I001

from importlib import import_module
from types import ModuleType

_SUPPORT_MODULE_NAMES = (
    "shared",
    "builders",
    "fakes_model",
    "fakes_tools",
    "fakes_financial",
    "fakes_more",
)

_support_modules: tuple[ModuleType, ...] = tuple(
    import_module(f"{__package__}.{module_name}") for module_name in _SUPPORT_MODULE_NAMES
)
_exports: dict[str, object] = {}
for _support_module in _support_modules:
    for _name in getattr(_support_module, "__all__", ()):  # pragma: no branch
        _exports[_name] = getattr(_support_module, _name)

for _support_module in _support_modules:
    _support_module.__dict__.update(_exports)

globals().update(_exports)
__all__ = tuple(_exports)
