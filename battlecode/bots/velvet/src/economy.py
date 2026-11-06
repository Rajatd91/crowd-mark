"""Economy: what to buy, and when carried gems should be banked.

Banking is an inventory-under-risk problem. Carried gems are lost on death,
and banking costs a round trip. The threshold is the closed form in
models.bank_threshold. Its inputs are estimated online, per champion:

- gem income rate: EWMA of gems gained per round on the map
- death hazard: Gamma-Poisson posteriors, one for calm play and one for when
  enemies have been seen recently, seeded by priors calibrated from
  self-play (research/calibrate.py)
"""
import math

import cambc
from cambc import constants as K

from models import Ewma, GammaRate, bank_threshold
from params import PARAMS

F, S, CT = cambc.ItemFamily, cambc.ItemStat, cambc.ChampionType

STRENGTH_BUILD = [(F.JUNGLE, S.STRENGTH, 1), (F.MONSTER, S.STRENGTH, 1), (F.POWER, S.STRENGTH, 1),
                  (F.DURABILITY, S.HEALTH, 1), (F.POWER, S.STRENGTH, 2), (F.POWER, S.HEALTH, 1),
                  (F.POWER, S.STRENGTH, 3), (F.POWER, S.STRENGTH, 4), (F.POWER, S.STRENGTH, 6)]
TANK_BUILD = [(F.JUNGLE, S.HEALTH, 1), (F.MONSTER, S.STRENGTH, 1), (F.DURABILITY, S.HEALTH, 1),
              (F.POWER, S.STRENGTH, 1), (F.POWER, S.HEALTH, 1), (F.POWER, S.STRENGTH, 2),
              (F.POWER, S.HEALTH, 2), (F.POWER, S.STRENGTH, 4)]
TANKS = (int(CT.RYTH), int(CT.MARCELLA))


class Economy:
    def __init__(self, kind):
        self.build = TANK_BUILD if kind in TANKS else STRENGTH_BUILD
        prior = PARAMS["hazard_prior_rounds"]
        self.hazard_calm = GammaRate(PARAMS["hazard_calm"], prior)
        self.hazard_threat = GammaRate(PARAMS["hazard_threat"], prior / 4)
        self.gem_rate = Ewma(PARAMS["gem_rate_prior"], PARAMS["gem_rate_half_life"])
        self.last_gems = 0
        self.was_alive = True
        self.last_threat = -10_000
        self.threatened = False

    # ----------------------------------------------------------- estimation
    def track(self, me, round_number, enemies_seen, on_map):
        """Per-turn update of the hazard posteriors and the gem income rate."""
        alive = me.is_alive()
        if enemies_seen:
            self.last_threat = round_number
        self.threatened = round_number - self.last_threat <= PARAMS["threat_memory"]
        bucket = self.hazard_threat if self.threatened else self.hazard_calm
        if self.was_alive and not alive:
            bucket.observe(1, 0)
            self.last_gems = 0
        elif alive and on_map:
            bucket.observe(0, 1)
            gems = me.gem_count()
            if not (me.is_submitting_gems()):
                self.gem_rate.update(max(0, gems - self.last_gems))
            self.last_gems = gems
        self.was_alive = alive

    def hazard(self):
        return (self.hazard_threat if self.threatened else self.hazard_calm).mean

    # -------------------------------------------------------------- banking
    def threshold(self, altar_distance):
        trip = 2 * altar_distance + 3
        g = bank_threshold(self.gem_rate.value, self.hazard(), trip)
        if not math.isfinite(g):
            g = PARAMS["bank_max"]
        return min(max(g, PARAMS["bank_min"]), PARAMS["bank_max"])

    def should_bank(self, gems, altar_distance, round_number, enemies=False):
        if gems <= 0 or altar_distance >= 60000:
            return False
        if K.MAX_ROUNDS - round_number < altar_distance + gems // 10 + 25:
            return True                       # carried gems are worth nothing at the end
        if PARAMS["bank_model"] == "fixed":   # the hand-tuned rules of earlier versions
            return (enemies and gems >= 8) or gems >= 36 or (gems >= 14 and altar_distance <= 10)
        if altar_distance <= 2 and gems >= 3:
            return True                       # the trip is nearly free
        return gems >= self.threshold(altar_distance)

    # ------------------------------------------------------------- shopping
    def shop(self, me):
        try:
            gold = me.gold_count()
            if gold < 30:
                return
            counts = me.item_count()
            for family, stat, wanted in self.build:
                emblem = cambc.get_item_enum(family, stat, False)
                if counts[int(emblem)] >= wanted:
                    continue
                shard = cambc.get_item_enum(family, stat, True)
                per = 25 if family == F.GREED else 5
                need = per - counts[int(shard)]
                cost = shard.cost()
                n = min(need, gold // cost)
                if n <= 0 or not me.can_buy(shard, n):
                    return
                me.buy(shard, n)
                gold -= n * cost
                if n < need:
                    return
                counts = me.item_count()
        except Exception as error:
            print(f"shop: {error!r}", flush=True)

    @staticmethod
    def has_emblem(me, family):
        try:
            counts = me.item_count()
            return any(counts[int(cambc.get_item_enum(family, s, False))] for s in (S.STRENGTH, S.HEALTH, S.FOCUS))
        except Exception:
            return False
