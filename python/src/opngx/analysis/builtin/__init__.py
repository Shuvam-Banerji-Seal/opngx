"""Modules that ship with opngx. Listed explicitly (not discovered by
walking the package) so frozen builds (PyInstaller) always include them."""

BUILTIN = ("motion_tracking", "brownian", "luminosity", "contrast", "focus", "drift", "particles", "flicker", "roi_stats")
