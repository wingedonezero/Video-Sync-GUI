# Import-side-effect helper to ensure settings are loaded before UI build.
from vsg.settings_core import preload_from_disk
preload_from_disk()
