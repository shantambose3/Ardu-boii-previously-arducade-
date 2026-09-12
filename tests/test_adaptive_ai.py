"""
Deterministic unit tests for game/adaptive_ai.py -- PlayerProfile,
BossLearner, and ChaosDirector.

Run from ardu-cade/:
    pip install pytest --break-system-packages
    PYTHONPATH=python/galactic_raiders pytest tests/test_adaptive_ai.py -v

These deliberately test the pure-Python logic in adaptive_ai.py only
(no pygame/display dependency), so they run fine in CI or on a laptop
with no game assets or a display available.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python", "galactic_raiders"))

from game.adaptive_ai import PlayerProfile, BossLearner, ChaosDirector  # noqa: E402


# ---------------------------------------------------------------------
# PlayerProfile
# ---------------------------------------------------------------------

def test_favorite_weapon_tracks_most_used():
    p = PlayerProfile()
    for _ in range(5):
        p.observe_weapon("B")
    assert p.favorite_weapon() == "B"


def test_favorite_bucket_tracks_position():
    p = PlayerProfile()
    # bucket 4 (bottom of a 0..world_height range, since bucket = y/height*5)
    for _ in range(20):
        p.observe_position(950, 1000)
    assert p.favorite_bucket() == 4


def test_accuracy_neutral_until_enough_samples():
    p = PlayerProfile()
    p.observe_shot_fired("A")
    p.observe_shot_hit("A")
    # fewer than 5 shots fired -> neutral 0.5, not 1.0
    assert p.accuracy() == 0.5


def test_accuracy_reflects_hit_rate_once_seeded():
    p = PlayerProfile()
    for _ in range(10):
        p.observe_shot_fired("A")
    for _ in range(3):
        p.observe_shot_hit("A")
    assert abs(p.accuracy() - 0.3) < 1e-9


def test_accuracy_is_clamped_and_multi_weapon():
    p = PlayerProfile()
    for _ in range(6):
        p.observe_shot_fired("A")
        p.observe_shot_hit("A")
    for _ in range(4):
        p.observe_shot_fired("B")
    assert p.accuracy() == 0.6  # 6 hits / 10 fired


def test_reaction_time_norm_is_higher_for_faster_reactions():
    fast = PlayerProfile()
    fast.observe_reaction_time(0.15)
    slow = PlayerProfile()
    slow.observe_reaction_time(1.2)
    assert fast.reaction_time_norm() > slow.reaction_time_norm()


def test_risk_tolerance_defaults_then_tracks_samples():
    p = PlayerProfile()
    assert p.risk_tolerance() == 0.3  # documented neutral default
    p.observe_risk_sample(1.0)
    p.observe_risk_sample(0.0)
    assert p.risk_tolerance() == 0.5


def test_feature_vector_shape_and_range():
    p = PlayerProfile()
    p.observe_aggression(0.8)
    vec = p.feature_vector()
    assert len(vec) == 4
    for v in vec:
        assert 0.0 <= v <= 1.0


def test_suggested_dive_rate_multiplier_scales_with_aggression():
    passive = PlayerProfile()
    passive.observe_aggression(0.0)
    aggressive = PlayerProfile()
    aggressive.observe_aggression(1.0)
    assert aggressive.suggested_dive_rate_multiplier() > passive.suggested_dive_rate_multiplier()
    assert 0.7 <= passive.suggested_dive_rate_multiplier() <= 1.7


def test_to_dict_from_dict_round_trip():
    p = PlayerProfile()
    for _ in range(8):
        p.observe_shot_fired("X")
    for _ in range(4):
        p.observe_shot_hit("X")
    p.observe_weapon("X")
    p.observe_aggression(0.7)
    p.observe_reaction_time(0.4)
    p.observe_risk_sample(0.9)

    data = p.to_dict()
    restored = PlayerProfile.from_dict(data)

    assert restored.favorite_weapon() == "X"
    assert abs(restored.accuracy() - p.accuracy()) < 1e-6
    assert abs(restored.avg_aggression() - p.avg_aggression()) < 1e-6
    assert abs(restored.avg_reaction_time() - p.avg_reaction_time()) < 1e-6
    assert abs(restored.risk_tolerance() - p.risk_tolerance()) < 1e-6


def test_from_dict_handles_missing_and_malformed_data():
    assert isinstance(PlayerProfile.from_dict(None), PlayerProfile)
    assert isinstance(PlayerProfile.from_dict({}), PlayerProfile)
    assert isinstance(PlayerProfile.from_dict({"weapon_usage": "not a dict"}), PlayerProfile)


# ---------------------------------------------------------------------
# BossLearner
# ---------------------------------------------------------------------

def test_boss_learner_counter_weapon():
    b = BossLearner()
    b.observe_damage("A", 10)
    b.observe_damage("B", 40)
    b.observe_damage("X", 5)
    assert b.counter_weapon() == "B"


def test_boss_learner_preferred_evade_direction():
    b = BossLearner()
    for _ in range(5):
        b.observe_dodge(-1)  # player dodges up a lot
    # boss should drift toward the side dodged LESS (down = +1)
    assert b.preferred_evade_direction() == 1


def test_boss_learner_difficulty_scale_increases_with_hits_taken():
    b = BossLearner()
    start = b.scale()
    for _ in range(10):
        b.observe_hit_taken()
    assert b.scale() > start
    assert b.scale() <= 2.2  # documented cap


def test_boss_learner_taunt_requires_min_hits_and_fires_once_per_shift():
    b = BossLearner()
    names = {"A": "VACUUM NAILS", "B": "MJOLNIR"}
    b.observe_damage("A", 100)
    assert b.pending_taunt("TESTBOSS", names) is None  # not enough hits yet
    for _ in range(3):
        b.observe_hit_taken()
    taunt = b.pending_taunt("TESTBOSS", names)
    assert taunt is not None
    assert "VACUUM NAILS" in taunt
    # same counter weapon -> no repeat taunt
    assert b.pending_taunt("TESTBOSS", names) is None
    # counter weapon shifts -> a new taunt fires
    b.observe_damage("B", 500)
    taunt2 = b.pending_taunt("TESTBOSS", names)
    assert taunt2 is not None and "MJOLNIR" in taunt2


# ---------------------------------------------------------------------
# ChaosDirector
# ---------------------------------------------------------------------

def test_chaos_director_is_deterministic_with_a_seed():
    a = ChaosDirector(seed=123)
    b = ChaosDirector(seed=123)
    events_a = [a.update(0.5) for _ in range(60)]
    events_b = [b.update(0.5) for _ in range(60)]
    assert events_a == events_b


def test_chaos_director_eventually_fires_an_event():
    c = ChaosDirector(seed=7)
    fired = [c.update(0.25) for _ in range(200)]
    assert any(e is not None for e in fired)
    assert all(e in ChaosDirector.EVENTS for e in fired if e is not None)


def test_chaos_director_is_active_matches_last_event():
    c = ChaosDirector(seed=7)
    event = None
    for _ in range(200):
        result = c.update(0.25)
        if result:
            event = result
            break
    assert event is not None
    assert c.is_active(event)
    assert c.label_for(event) == ChaosDirector.EVENT_LABELS[event]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
