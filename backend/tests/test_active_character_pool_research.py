"""Rolling limit-up activity and campaign checks."""
import importlib

import numpy as np
import pytest


@pytest.fixture
def research(monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("research_active_character_pool")


def test_consecutive_limits_share_campaign_but_refresh_freshness(research):
    hits = np.zeros((70, 1), dtype=bool)
    hits[[2, 3, 10], 0] = True
    age, campaign_age, last, campaign = research.activity_state(hits)
    assert age[2:5, 0].tolist() == [0, 0, 1]
    assert campaign_age[2:5, 0].tolist() == [0, 1, 2]
    assert campaign[3, 0] == 2 and last[3, 0] == 3
    assert age[10, 0] == 0 and campaign_age[10, 0] == 0
    assert age[69, 0] == 59 and age.shape == campaign_age.shape


def test_activity_expires_after_sixty_market_sessions(research):
    hits = np.zeros((62, 1), dtype=bool)
    hits[0, 0] = True
    age, _, _, _ = research.activity_state(hits)
    assert age[59, 0] == 59
    assert age[60, 0] == -1
