from __future__ import annotations


class PluginEngineError(RuntimeError):
    """Base class for plugin engine failures."""


class PluginManifestError(PluginEngineError):
    """Raised when a plugin manifest is invalid."""


class PluginLoadError(PluginEngineError):
    """Raised when a plugin cannot be loaded."""


class PluginTypeError(PluginEngineError):
    """Raised when a plugin does not support the requested plugin type."""

