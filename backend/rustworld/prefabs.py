"""Rust prefab identity.

Every prefab in Rust is addressed on the wire by a ``uint32`` id.  The game
builds that id in ``StringPool`` from ``GameManifest.pooledStrings``; new
strings are registered with ``StringPool.Add`` which calls
``str.ManifestHash()``.

That hash is simply the **first four bytes of the MD5 digest of the asset
path, read little-endian**::

    id = uint32_le(md5(path)[:4])

This was recovered empirically and verified against 38 known
(path, id) pairs taken from the Carbon prefab dump
(``https://api.carbonmod.gg/meta/rust/prefabs.json``) — see
``tests/test_prefabs.py`` for the verification vectors.

Being able to *compute* ids means we do not need to ship (or keep in sync)
a path -> id lookup table: any prefab the game knows about can be written
into a ``.map`` file straight from its asset path.

Paths are matched case-insensitively by the game (``StringPool.toNumber``
uses ``OrdinalIgnoreCase``) but the pooled string itself is the lowercase
asset path, so we normalise to lowercase before hashing.
"""
from __future__ import annotations

import hashlib
import struct

__all__ = ["prefab_id", "normalise_path", "MONUMENT_CATEGORY"]

# PrefabData.category is a free-form label; RustEdit writes the monument's
# folder name.  The server ignores it, so a stable marker is fine.
MONUMENT_CATEGORY = "Monument"


def normalise_path(path: str) -> str:
    """Normalise an asset path to the form used in the game manifest."""
    return path.strip().replace("\\", "/").lower()


def prefab_id(path: str) -> int:
    """Return the ``uint32`` StringPool id for an asset path.

    >>> prefab_id("assets/prefabs/player/player.prefab")
    4108440852
    """
    digest = hashlib.md5(normalise_path(path).encode("utf-8")).digest()
    return struct.unpack("<I", digest[:4])[0]
