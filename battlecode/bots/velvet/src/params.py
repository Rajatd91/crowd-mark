"""Tunable parameters. research/tune.py writes variants of this file; values
here are the ones that won the most recent tuning run (research/results/).

Keep every value a plain literal: the tuner rewrites this file textually.
"""
PARAMS = {
    # Farming value of gold relative to gems, early game (fades linearly to 0).
    "gold_weight": 0.12,
    # Groups with less health than this are one champion's job.
    "small_group_hp": 1600,
    # Squad planning: per-champion damage and health assumptions.
    "team_dps_each": 70.0,
    "team_hp_each": 900.0,
    # Allies that must be near before the squad wakes a sleeping big group.
    "gather": 2,
    # Hysteresis on the current target, to stop flip-flopping.
    "stickiness": 1.3,
    # Health fraction below which we disengage from camps and recall.
    "retreat_health": 0.38,
    # Banking model: prior death hazard per round (Gamma prior mean) on the
    # map, without and with enemies seen recently, and the prior's strength
    # in rounds. Calibrated from backtest data (research/calibrate.py measured
    # 0.006 deaths per alive round overall, higher near enemies).
    "hazard_calm": 0.003,
    "hazard_threat": 0.02,
    "hazard_prior_rounds": 600.0,
    # Prior gem income per round while farming (calibrated: 0.11-0.12 measured),
    # and the EWMA half-life in rounds.
    "gem_rate_prior": 0.12,
    "gem_rate_half_life": 120.0,
    # Banking threshold is clamped to this range.
    "bank_min": 8,
    "bank_max": 90,
    # Team fights: engage when our Lanchester power is this multiple of theirs.
    "engage_ratio": 0.85,
    "chase_ratio": 1.4,
    # Rounds an enemy sighting keeps raising the threat level.
    "threat_memory": 25,
    # Draft preference order.
    "draft": ["cassi_issac", "vendetta", "tavi", "willow", "varg", "stellar",
              "ryth", "marcella", "prism", "vesper_vale", "ren", "heart_of_ruin"],
    # Ablation switches (research/tune.py turns these off to measure each model).
    "flee_enabled": False,      # ablation: fleeing cost more than it saved (fighting back wins)
    "decline_fights": True,     # use the Lanchester/duel model to decline optional fights
    "bank_model": "risk",       # "risk": closed-form threshold; "fixed": hand-set rules
}
