import os
import tempfile

# Prevent API tests from ever touching the owner's real data.
os.environ["JARVIS_DATA"] = tempfile.mkdtemp(prefix="jarvis-test-suite-")

os.environ["JARVIS_WARMUP"] = "0"
os.environ["JARVIS_NEWS_SCHEDULER"] = "0"

import pytest
from jarvis.credentials import credentials


@pytest.fixture(autouse=True)
def isolated_credential_cache():
    credentials.reads.clear()
    yield
    credentials.reads.clear()
