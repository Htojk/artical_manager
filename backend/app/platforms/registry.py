"""Discovery and lookup of platform adapters."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import Iterable

from app.platforms.base import PlatformAdapter

logger = logging.getLogger(__name__)


class PlatformRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, PlatformAdapter] = {}

    def register(self, adapter: PlatformAdapter) -> None:
        if not getattr(adapter, "key", None):
            raise ValueError("adapter.key is required")
        self._adapters[adapter.key] = adapter

    def get(self, key: str) -> PlatformAdapter | None:
        return self._adapters.get(key)

    def require(self, key: str) -> PlatformAdapter:
        adapter = self.get(key)
        if adapter is None:
            raise KeyError(f"unknown platform: {key}")
        return adapter

    def all(self) -> list[PlatformAdapter]:
        return sorted(self._adapters.values(), key=lambda item: item.key)

    def keys(self) -> list[str]:
        return sorted(self._adapters)

    def with_capability(self, capability: str) -> list[PlatformAdapter]:
        return [
            adapter
            for adapter in self.all()
            if getattr(adapter.capabilities, capability, False)
        ]

    def discover(
        self,
        *,
        package: str = "app.platforms",
        paths: Iterable[str | Path] | None = None,
    ) -> list[PlatformAdapter]:
        modules: list[str] = []
        if paths is None:
            base = importlib.import_module(package)
            for module_info in pkgutil.iter_modules(base.__path__):
                if module_info.ispkg:
                    modules.append(f"{package}.{module_info.name}.adapter")
            for module_name in modules:
                self._import_module(module_name)
        else:
            for index, path in enumerate(paths):
                root = Path(path)
                for adapter_file in sorted(root.glob("*/adapter.py")):
                    module_name = f"_external_adapter_{index}_{adapter_file.parent.name}"
                    spec = importlib.util.spec_from_file_location(module_name, adapter_file)
                    if spec is None or spec.loader is None:
                        logger.warning("cannot load adapter file %s", adapter_file)
                        continue
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    self._collect(module)
        return self.all()

    def _import_module(self, module_name: str) -> None:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            return
        except Exception:  # noqa: BLE001 - one broken platform must not block startup
            logger.exception("failed to import adapter module %s", module_name)
            return
        self._collect(module)

    def _collect(self, module: object) -> None:
        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(candidate, PlatformAdapter)
                and candidate is not PlatformAdapter
                and candidate.__module__ == getattr(module, "__name__", "")
            ):
                try:
                    self.register(candidate())
                except TypeError:
                    logger.exception("adapter %s cannot be instantiated", candidate)
                except Exception:  # noqa: BLE001
                    logger.exception("failed to register adapter %s", candidate)


registry = PlatformRegistry()
