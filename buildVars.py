# Build customizations
# Change this file instead of sconstruct or manifest files, whenever possible.

from site_scons.site_tools.NVDATool.typings import (
    AddonInfo,
    BrailleTables,
    SymbolDictionaries,
)

# Since some strings in `addon_info` are translatable,
# we need to include them in the .po files.
# Gettext recognizes only strings given as parameters to the `_` function.
# To avoid initializing translations in this module we simply import a "fake" `_` function
# which returns whatever is given to it as an argument.
from site_scons.site_tools.NVDATool.utils import _

# Add-on information variables
addon_info = AddonInfo(
    addon_name="dengjen_neural_voices",
    # Add-on summary/title, usually the user visible name of the add-on
    # Translators: Summary/title for this add-on
    # to be shown on installation and add-on information found in add-on store
    addon_summary=_("Dengjen Neural Voices"),
    # Add-on description
    # Translators: Long description to be shown for this add-on on add-on information from add-on store
    addon_description=_(
        """Adds fast, local neural text-to-speech voices to NVDA. Provides a synthesizer driver for Piper voice models via the dengjen engine, together with a voice manager for downloading and installing voices."""
    ),
    addon_version="4.0.1",
    # Brief changelog for this version
    # Translators: what's new content for the add-on version to be shown in the add-on store
    addon_changelog=_(
        "Corrected the declared minimum NVDA version to 2026.1. "
        "The bundled speech engine has required NVDA's Python 3.13 64-bit runtime since v3.2-beta.1; "
        "the add-on previously claimed support for NVDA 2025.1+ and failed to load with an ImportError "
        "on those older, incompatible NVDA versions."
    ),
    addon_author="Musharraf Omer (original) <ibnomer2011@hotmail.com>, Ali Ustek (maintainer) <13117393+austek@users.noreply.github.com>",
    addon_url="https://github.com/zirekhq/dengjen-nvda",
    addon_sourceURL="https://github.com/zirekhq/dengjen-nvda",
    addon_docFileName="readme.html",
    addon_minimumNVDAVersion="2026.1",
    addon_lastTestedNVDAVersion="2026.1",
    # Add-on update channel (default is None, denoting stable releases,
    # and for development releases, use "dev".)
    # Do not change unless you know what you are doing!
    addon_updateChannel=None,
    addon_license="GPL 2",
    addon_licenseURL="https://www.gnu.org/licenses/old-licenses/gpl-2.0.html",
)

pythonSources: list[str] = [
    "addon/globalPlugins/*/*.py",
    "addon/synthDrivers/*/*.*",
    # The clean-architecture subpackages (domain/, ports/, adapters/*/) nest
    # one level deeper than the flat layout the glob above was written for.
    # Vendored/generated code (lib/, adapters/sonata_grpc/grpc_protos/) stays
    # out on purpose -- these globs go exactly one level deeper, not
    # recursive.
    "addon/synthDrivers/*/domain/*.py",
    "addon/synthDrivers/*/ports/*.py",
    "addon/synthDrivers/*/adapters/*.py",
    "addon/synthDrivers/*/adapters/*/*.py",
]

i18nSources: list[str] = pythonSources + ["buildVars.py", "addon/installTasks.py"]

excludedFiles: list[str] = []

baseLanguage: str = "en"

markdownExtensions: list[str] = []

brailleTables: BrailleTables = {}
symbolDictionaries: SymbolDictionaries = {}
