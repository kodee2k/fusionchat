"""Pytest fixtures shared across the suite."""
from __future__ import annotations

import pytest

import fusionchat.web as web


@pytest.fixture(autouse=True)
def _clear_web_sessions():
    web.SESSIONS.clear()
    yield
    web.SESSIONS.clear()
