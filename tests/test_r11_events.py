# -*- coding: utf-8 -*-
"""R11.4/M1：构筑对手类型赛事适用范围。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.stats import is_constructed_opponent_event as f


def test_ladder_and_play():
    assert f("Ladder") is True
    assert f("Traditional_Ladder") is True
    assert f("Play") is True
    assert f("Play_Brawl_Historic") is False


def test_draft_sealed_brawl_excluded():
    assert f("PremierDraft_LCI") is False
    assert f("Trad_Sealed_LCI") is False
    assert f("Brawl_Challenge_Historic") is False


def test_mwm_constructed_included():
    assert f("MWM_Historic_AllAccess") is True
    assert f("MWM_Explorer_AllAccess") is True
    assert f("MWM_HistoricArtisan") is True
    assert f("MWM_Pauper") is True
    assert f("MWM_Standard") is True
    assert f("MWM_Timeless") is True


def test_mwm_special_excluded():
    assert f("MWM_Momir_20260908") is False
    assert f("MWM_Historic_Brawl") is False


def test_decathlon_constructed():
    assert f("Decathlon_Standard") is True
    assert f("Decathlon_PremierDraft_X") is False  # 含 Draft 先排除


def test_empty_and_unknown():
    assert f(None) is False
    assert f("") is False
    assert f("SomeRandomEvent") is False
