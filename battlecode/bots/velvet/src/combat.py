"""Combat: casting, attacking, support, and the champion-fight decision.

Team fights use Lanchester's square law. Each visible unit within reach
counts as (damage rate, health); the side with the larger product of the
totals is expected to win. We engage when our power ratio clears a tuned
threshold, and prefer the target with the best reward per round of kill time.
That target is often the one carrying gems, because killing a champion takes
its whole bag.
"""
import cambc
from cambc import vision, Team

from models import CAMP_STATS, duel_win_probability, fight_ratio, target_value
from params import PARAMS
from world import camp_kind


def unit_dps(champion):
    """Rough damage per round of a visible champion: strength plus ability damage amortised."""
    try:
        return max(champion.strength() + champion.focus() * 0.25, 1.0)
    except Exception:
        return 40.0


class Combat:
    def __init__(self, nav):
        self.nav = nav

    # ------------------------------------------------------------- primitives
    def burst(self, me):
        total = me.strength()
        for ability in me.abilities():
            try:
                if ability.is_ready() and (ability.is_damage() or ability.is_aoe_damage()):
                    total += ability.damage_amount()
                elif ability.is_ready() and ability.is_attack_reset():
                    total += me.strength()
            except Exception:
                pass
        return total

    def camp_dps(self, me):
        strength = me.strength()
        try:
            strength *= me.base_stats().camp_damage_multiplier or 1.0
        except Exception:
            pass
        dps = strength
        for ability in me.abilities():
            try:
                if ability.is_attack_reset():
                    dps += strength / 8
                elif (ability.is_damage() or ability.is_aoe_damage()) and (
                        ability.can_target_camps() or ability.can_target_ground()):
                    dps += ability.damage_amount() / 8
            except Exception:
                pass
        return max(dps, 1.0)

    def strike(self, me, target):
        """Cast, attack and reset against one unit. Returns True if anything happened."""
        acted = False
        try:
            if me.can_cast() and self.cast_offensive(me, target):
                acted = True
            if not target.is_visible():
                return acted
            if me.can_attack() and me.attack_tiles().is_set(target.position()) and target.health() > 0:
                me.attack(target)
                acted = True
                if me.can_cast() and not me.can_attack():
                    for ability in me.abilities():
                        if ability.is_ready() and ability.is_attack_reset():
                            if ability.use() and target.is_visible() and me.can_attack():
                                me.attack(target)
                            break
        except Exception as error:
            if "not in vision" not in str(error):
                print(f"strike: {error!r}", flush=True)
        return acted

    def cast_offensive(self, me, target):
        tpos = target.position()
        is_camp = isinstance(target, cambc.Camp)
        harmless = is_camp and CAMP_STATS[camp_kind(target)][1] == 0
        for ability in me.abilities():
            try:
                if not ability.is_ready():
                    continue
                if ability.is_heal() or ability.is_shield() or ability.is_dash() or ability.is_attack_reset():
                    continue
                if not (ability.is_damage() or ability.is_aoe_damage() or ability.is_cc()):
                    continue
                if harmless and not (ability.is_damage() or ability.is_aoe_damage()):
                    continue          # never waste a pure stun on a gem cluster
                if not ability.valid_tiles().is_set(tpos):
                    continue
                unit_ok = ability.can_target_camps() if is_camp else ability.can_target_enemies()
                if unit_ok and ability.use(target):
                    return True
                if not unit_ok and ability.can_target_ground() and ability.use(tpos):
                    return True
            except Exception:
                continue
        return False

    def support(self, me, under_fire):
        """Heal the most wounded ally in range, or shield ourselves under fire."""
        if not me.can_cast():
            return False
        for ability in me.abilities():
            try:
                if not ability.is_ready():
                    continue
                if ability.is_heal():
                    best = None
                    for ally in vision.champions(Team.ALLY):
                        if ally == me or not ally.is_alive():
                            continue
                        missing = ally.max_health() - ally.health()
                        if missing > 0.5 * ability.heal_amount() and ability.valid_tiles().is_set(ally.position()):
                            if best is None or missing > best[0]:
                                best = (missing, ally)
                    if best and ability.use(best[1]):
                        return True
                if ability.is_shield() and under_fire and me.health() < 0.85 * me.max_health():
                    if ability.use():
                        return True
            except Exception:
                continue
        return False

    # --------------------------------------------------------------- decision
    def assess(self, me, enemies):
        """Lanchester ratio of the local fight around us, and enemies within reach."""
        pos = me.position()
        near_enemies, theirs = [], []
        for enemy in enemies:
            try:
                d = pos.chebyshev_distance(enemy.position())
            except Exception:
                continue
            if d <= 7:
                try:
                    theirs.append((unit_dps(enemy), max(enemy.health(), 1.0)))
                except Exception:
                    continue
                near_enemies.append((d, enemy))
        ours = [(unit_dps(me), me.health())]
        for ally in vision.champions(Team.ALLY):
            try:
                if ally != me and ally.is_alive() and ally.position().chebyshev_distance(pos) <= 5:
                    ours.append((unit_dps(ally), ally.health()))
            except Exception:
                continue
        return (fight_ratio(ours, theirs) if theirs else float("inf")), near_enemies, len(ours)

    def fight(self, me, enemies):
        """Take or decline a champion fight. Returns True if the turn was spent on it."""
        if not enemies:
            return False
        ratio, near, allies = self.assess(me, enemies)
        if not near:
            return False
        pos = me.position()
        my_dps = max(me.strength(), 1.0)
        burst = self.burst(me)
        in_reach = []
        for d, enemy in near:
            try:
                reach = max(enemy.attack_range(), 4 if enemy.attack_range() > 1 else 2)
            except Exception:
                reach = 3
            if d <= max(me.attack_range(), reach):
                in_reach.append(enemy)
        if in_reach:
            # Already in the fight: fleeing loses (equal speed, recall breaks on damage),
            # so fight unless clearly outmatched with an escape route home.
            if PARAMS["decline_fights"] and ratio < 0.35 and me.health() < 0.3 * me.max_health():
                return False
            pool = in_reach
        elif not PARAMS["decline_fights"]:
            # Baseline policy: chase only enemies our burst can finish.
            pool = []
            for d, e in near:
                try:
                    if e.health() <= burst * 1.2 and d <= me.attack_range() + 2:
                        pool.append(e)
                except Exception:
                    continue
            if not pool:
                return False
        else:
            # Optional fight: only when the numbers say we win, or a 1v1 duel is likely won.
            if ratio < PARAMS["chase_ratio"]:
                if len(near) == 1 and allies == 1:
                    e = near[0][1]
                    try:
                        p = duel_win_probability(me.health(), my_dps, burst, e.health(), unit_dps(e),
                                                 e.focus() * 1.5, we_act_first=True)
                    except Exception:
                        p = 0.0
                    if p < 0.75:
                        self._avoid(near)
                        return False
                else:
                    self._avoid(near)
                    return False
            pool = [e for _, e in near]

        def value(enemy):
            try:
                return target_value(enemy.gem_count(), enemy.health(), my_dps)
            except Exception:
                return 0.0
        target = max(pool, key=value)
        if self.strike(me, target):
            if me.can_move() and me.attack_range() == 1:
                self.nav.approach(target)
            return True
        if me.can_move():
            self.nav.approach(target)
            self.strike(me, target)
        return True

    def _avoid(self, near):
        """Mark the reach of enemies we decline to fight as a no-go zone for pathing."""
        from world import ring
        for _, enemy in near:
            try:
                self.nav.threat_zone |= ring(enemy.position(), enemy.attack_range() + 1)
            except Exception:
                continue
