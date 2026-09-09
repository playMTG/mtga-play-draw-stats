# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

@pytest.fixture(autouse=True)
def isolated_card_names(tmp_path, monkeypatch):
    # Tests must not depend on the developer's downloaded name catalog.
    from app import card_names
    monkeypatch.setattr(card_names, 'ROOT', tmp_path)
