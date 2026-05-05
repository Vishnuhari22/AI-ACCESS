"""
Audio Privacy Module — detects whether audio output is routed to a private
device (headphones/earbuds) so the system can avoid speaking sensitive data
over public speakers.
"""
import subprocess

_HEADPHONE_KEYWORDS = [
    'headphone', 'headset', 'earphone', 'earbud',
    'airpod', 'buds', 'in-ear', 'bluetooth audio',
    'wh-1000', 'wf-1000', 'galaxy buds', 'jabra',
    'hands-free', 'bose', 'sennheiser', 'jbl',
]

# Cache result for N seconds to avoid repeated subprocess calls
_cache = {"result": None, "timestamp": 0}
_CACHE_TTL = 10  # seconds


def is_headphone_connected() -> bool:
    """
    Best-effort check for whether audio is routed to a private output device.

    Returns True if headphones/earbuds appear to be the active audio output.
    Returns False (safe default: assume public speakers) if detection fails.
    """
    import time
    now = time.time()
    if _cache["result"] is not None and (now - _cache["timestamp"]) < _CACHE_TTL:
        return _cache["result"]

    result = _try_pycaw() or _try_powershell()
    _cache["result"] = result
    _cache["timestamp"] = now
    return result


def _try_pycaw() -> bool:
    """Attempt detection using pycaw (Python Core Audio Windows)."""
    try:
        from pycaw.pycaw import AudioUtilities
        devices = AudioUtilities.GetAllDevices()
        for d in devices:
            name = (d.FriendlyName or "").lower()
            if any(kw in name for kw in _HEADPHONE_KEYWORDS):
                return True
        return False
    except ImportError:
        return False
    except Exception as e:
        print(f"[AudioPrivacy] pycaw error: {e}")
        return False


def _try_powershell() -> bool:
    """Fallback: query PnP audio endpoint devices via PowerShell."""
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             'Get-PnpDevice -Class AudioEndpoint -Status OK 2>$null '
             '| Select-Object -ExpandProperty FriendlyName'],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000  # CREATE_NO_WINDOW
        )
        if result.returncode == 0 and result.stdout.strip():
            names = result.stdout.strip().lower()
            return any(kw in names for kw in _HEADPHONE_KEYWORDS)
    except Exception as e:
        print(f"[AudioPrivacy] PowerShell fallback error: {e}")
    return False
