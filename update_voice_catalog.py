import importlib.util
import json
import sys
import urllib.request
from pathlib import Path

PIPER_SOURCES_FILE = (
    Path(__file__).parent
    / "addon/globalPlugins/dengjen_tts_global_plugin/piper_sources.py"
)
_spec = importlib.util.spec_from_file_location("piper_sources", PIPER_SOURCES_FILE)
piper_sources = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(piper_sources)
PIPER_VOICE_LIST_URL = (
    f"{piper_sources.PIPER_VOICES_REPO_URL}/raw/"
    f"{piper_sources.PIPER_VOICES_REVISION}/voices.json"
)
RT_VOICE_LIST_URL = f"{piper_sources.PIPER_RT_REPO_URL}/raw/main/voices.json"
TARGET_PATH = (
    Path(__file__).parent
    / "addon/synthDrivers/dengjen_neural_voices/data/piper-voices.json"
)


def _fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode())


print(f"Fetching {PIPER_VOICE_LIST_URL}...")
try:
    std_voices = _fetch_json(PIPER_VOICE_LIST_URL)
except Exception as e:
    print(f"Failed to fetch the standard voice list: {e}")
    sys.exit(1)

print(f"Fetching {RT_VOICE_LIST_URL}...")
try:
    rt_voices = _fetch_json(RT_VOICE_LIST_URL)
except Exception as e:
    print(f"Failed to fetch the RT voice list: {e}")
    sys.exit(1)

# Mirrors voice_download._refresh_voices_cache(): flags every standard voice
# that has a matching fast (+RT) variant, same shape get_available_voices()
# expects whether it's reading the user's local cache or this bundled file.
rt_voice_names = {vdata["base"] for vdata in rt_voices.values()}
voice_list = {}
for vname, vdata in std_voices.items():
    vdata["has_rt_variant"] = vname in rt_voice_names
    voice_list[vname] = vdata

with open(TARGET_PATH, "w", encoding="utf-8") as f:
    json.dump(voice_list, f, ensure_ascii=False, indent=2)

print(f"Wrote {len(voice_list)} voices to {TARGET_PATH}")
