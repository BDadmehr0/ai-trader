"""Test helpers: point the disk cache and the settings file at a temp folder."""

import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import utils.cache


@contextmanager
def isolated_cache():
    """Keep test runs from reading or writing data/cache/."""
    folder = Path(tempfile.mkdtemp(prefix="aitrader-cache-"))
    with mock.patch.object(utils.cache, "CACHE_ROOT", folder), \
            mock.patch.dict(utils.cache._INSTANCES, {}, clear=True):
        yield folder
