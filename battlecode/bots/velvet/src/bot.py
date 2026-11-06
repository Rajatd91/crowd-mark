"""Champion controller: one instance per champion, one decision per turn.

Priority order each turn:
    1. shop (spawn, while dead, or anywhere for Tavi)
    2. champion fights        -> combat.Combat.fight (Lanchester / duel model)
    3. survival vs camps      -> retreat out of reach, then recall
    4. banking                -> economy.Economy.should_bank (risk-adjusted threshold)
    5. farming                -> best gems-per-round group, solo or as a squad

Farming is a rate maximisation. A solo target is scored as
value / (travel + kill + capture + healing trips). Squad targets, the big
groups, are planned by the leader with deaths priced as respawn downtime.
"""
import cambc
from cambc import vision, Team
from cambc import constants as K

from combat import Combat
from economy import Economy
from models import soak
from nav import Navigator
from params import PARAMS
from world import UNREACHABLE, Comms, World, ring, visible_camps

F, CT = cambc.ItemFamily, cambc.ChampionType
Bitboard = cambc.Bitboard


class Bot:
    def __init__(self):
        me = cambc.me()
        self.kind = int(me.champion_name())
        self.kind_name = str(me.champion_name())
        self.is_tavi = self.kind == int(CT.TAVI)
        self.world = World()
        self.comms = Comms(me)
        self.nav = Navigator(self.world)
        self.combat = Combat(self.nav)
        self.economy = Economy(self.kind)
        self.target = None
        self.commit = None            # (group index, start round, expected rounds)
        self.banned = {}              # group index -> round until which it is skipped
        self.note = "-"

    # ------------------------------------------------------------------ turn
    def play_turn(self):
        self.note = "-"
        me = cambc.me()
        self.me = me
        try:
            self.decide(me)
        finally:
            if cambc.round_number() % 50 == 0:
                self.report(me)

    def report(self, me):
        try:
            where = me.position() if me.is_alive() else "dead"
            print(f"r{cambc.round_number()} {self.kind_name} {where} hp={me.health():.0f}/{me.max_health():.0f} "
                  f"gems={me.gem_count()} gold={me.gold_count()} tgt={self.target} {self.note} "
                  f"bankG*={self.economy.threshold(self.world.altar_distance() if self.world.field else 20):.0f} "
                  f"haz={self.economy.hazard():.4f} rate={self.economy.gem_rate.value:.3f}", flush=True)
        except Exception as error:
            print(f"report: {error!r}", flush=True)

    def decide(self, me):
        world, comms = self.world, self.comms
        if not me.is_alive():
            self.economy.track(me, cambc.round_number(), False, False)
            self.economy.shop(me)
            comms.claim(None)
            return
        if me.is_recalling() or me.is_teleporting() or me.is_submitting_gems():
            self.economy.track(me, cambc.round_number(), False, False)
            return
        pos = me.position()
        world.refresh(pos)
        self.nav.new_turn(me)
        at_home = world.home.is_set(pos)
        enemies = [c for c in vision.champions(Team.ENEMY) if c.is_alive() and c.is_visible()]
        self.economy.track(me, world.round, bool(enemies), not at_home)
        if at_home or self.is_tavi:
            self.economy.shop(me)
        threats = self.threats(me, enemies)

        if at_home and me.health() < 0.9 * me.max_health() and not threats:
            comms.claim(None)
            self.note = "heal"
            return
        if self.combat.fight(me, enemies):
            self.note = "pvp"
            return
        if (PARAMS["flee_enabled"] and enemies and any(not isinstance(t, cambc.Camp) for t in threats)
                and (me.gem_count() >= 5 or me.health() < 0.5 * me.max_health())):
            self.note = "flee"                # outmatched and something to lose: keep the bag
            self.nav.home()
            return
        if self.survive(me, threats, at_home):
            self.note = "survive"
            return
        gems = me.gem_count()
        if self.economy.should_bank(gems, world.altar_distance(), world.round, bool(enemies)):
            self.note = f"bank {gems}"
            self.bank(me)
            return
        if self.should_shop(me, threats, at_home):
            self.note = "shop"
            me.recall()
            return
        self.farm(me)

    # -------------------------------------------------------------- survival
    def threats(self, me, enemies):
        pos = me.position()
        out = []
        for e in enemies:
            try:
                if pos.chebyshev_distance(e.position()) <= max(e.attack_range(), 4) + 1:
                    out.append(e)
            except Exception:
                pass
        for camp in visible_camps():
            try:
                if camp.is_awake() and pos.chebyshev_distance(camp.position()) <= camp.attack_range():
                    out.append(camp)
            except Exception:
                pass
        return out

    def survive(self, me, threats, at_home):
        self.combat.support(me, bool(threats))
        if at_home or me.health() >= PARAMS["retreat_health"] * me.max_health():
            return False
        if not threats:
            me.recall()
            return True
        if me.can_move():
            self.nav.home()           # camps never chase: step out of reach, recall next turn
        return True

    def should_shop(self, me, threats, at_home):
        if at_home or threats or self.is_tavi or me.gem_count() > 0:
            return False
        if self.world.round > K.MAX_ROUNDS - 250:
            return False
        gold = me.gold_count()
        return gold >= 300 or (gold >= 150 and me.health() < 0.6 * me.max_health())

    # --------------------------------------------------------------- banking
    def bank(self, me):
        pos = me.position()
        for altar in self.world.altars:
            if pos.chebyshev_distance(altar) <= K.SUBMIT_GEMS_RANGE:
                try:
                    me.submit_gems(altar)
                    self.comms.claim(None)
                    return
                except Exception as error:
                    print(f"submit: {error!r}", flush=True)
        if me.can_move():
            self.nav.step(self.world.altar_ring & ~self.nav.blocked(), dash=True)
            pos = me.position()
            for altar in self.world.altars:
                if pos.chebyshev_distance(altar) <= K.SUBMIT_GEMS_RANGE:
                    try:
                        me.submit_gems(altar)
                    except Exception:
                        pass
                    break

    # --------------------------------------------------------------- farming
    def solo_rate(self, me, group, distance, dps, claims):
        """Gems per round of taking this group alone, healing trips priced in."""
        if distance >= UNREACHABLE or self.banned.get(group.index, 0) > self.world.round:
            return None
        wait = 0
        if group.status == "respawn":
            wait = max(0, group.ready_at - self.world.round - distance)
            if wait > 30:
                return None
        small = group.hp < PARAMS["small_group_hp"]
        if small and group.index in self.comms.below:
            return None                       # a lower slot holds it
        helpers = 0 if small else claims.get(group.index, 0)
        hp = 0 if group.status == "reward" else group.hp
        team_dps = dps * (1 + 0.8 * helpers)
        kill = hp / team_dps
        damage = 0.0
        if hp > 0:
            damage = soak(group.monsters, team_dps, hp / max(group.max_hp, 1)) / (1 + helpers)
            if self.economy.has_emblem(me, F.JUNGLE):
                damage *= 0.7
        trips = 0
        if damage > 0.6 * me.health():
            trips = int((damage - 0.6 * me.health()) / (0.6 * me.max_health())) + 1
        if trips > 3:
            return None
        late = max(0.0, 1.0 - self.world.round / (K.MAX_ROUNDS * 0.8))
        value = group.gems + PARAMS["gold_weight"] * late * group.gold
        if value <= 0:
            return None
        if helpers:
            value *= 1.15
        rounds = distance + kill + K.CAPTURE_TIME + wait + trips * (2 * group.home_distance + 12) + 3
        return value / rounds

    def squad_cost(self, group, distance):
        """Team rounds to clear and capture a big group, deaths priced as respawn downtime."""
        n = self.comms.team_size
        team_dps = PARAMS["team_dps_each"] * n
        hp_each = PARAMS["team_hp_each"]
        kill = group.hp / team_dps
        damage = soak(group.monsters, team_dps, group.hp / max(group.max_hp, 1))
        deaths = max(0.0, (damage - 0.7 * hp_each * n) / hp_each)
        downtime = deaths * (K.RESPAWN_TIME + group.home_distance) / n
        return distance + kill + K.CAPTURE_TIME + 8 + downtime

    def plan_squad(self):
        """Leader only: pick the big group the team should take next."""
        current = self.comms.squad(self.world.groups)
        if current is not None and current.status == "alive" and current.hp < current.max_hp:
            return current
        if current is not None and current.status != "respawn" and self.world.round % 8:
            return current
        best = None
        for group in self.world.groups:
            if group.max_hp < PARAMS["small_group_hp"] or group.status == "respawn":
                continue
            distance = self.world.distance_to(group)
            if distance >= UNREACHABLE:
                continue
            rate = group.gems / self.squad_cost(group, distance)
            if best is None or rate > best[0]:
                best = (rate, group)
        target = best[1] if best else None
        self.comms.set_squad(target)
        return target

    def farm(self, me):
        world = self.world
        dps = self.combat.camp_dps(me)
        claims = self.comms.claims()
        best = None
        for group in world.groups:
            if group.hp >= PARAMS["small_group_hp"] and group.status != "reward":
                continue                      # big groups are squad business
            rate = self.solo_rate(me, group, world.distance_to(group), dps, claims)
            if rate is not None and self.commit and self.commit[0] == group.index:
                rate *= PARAMS["stickiness"]
            if rate is not None and (best is None or rate > best[0]):
                best = (rate, group, False)
        squad = self.plan_squad() if self.comms.slot == 0 else self.comms.squad(world.groups)
        if squad is not None and squad.status != "respawn" and self.banned.get(squad.index, 0) <= world.round:
            distance = world.distance_to(squad)
            if distance < UNREACHABLE:
                rate = squad.gems / self.comms.team_size / self.squad_cost(squad, distance) * 1.3
                if best is None or rate > best[0]:
                    best = (rate, squad, True)
        if best is None:
            self.note, self.target = "idle", None
            self.comms.claim(None)
            if me.gem_count() > 0:
                self.bank(me)
            elif me.can_move():
                self.nav.home()
            return
        rate, group, is_squad = best
        if self.commit is None or self.commit[0] != group.index:
            share = group.gems / (self.comms.team_size if is_squad else 1) + 1
            self.commit = (group.index, world.round, min(400, share / max(rate, 1e-3) * 1.6 + 30))
        elif world.round - self.commit[1] > self.commit[2]:
            self.banned[group.index] = world.round + 80     # far slower than planned: something unseen blocks us
            self.commit = None
            self.note = "stuck"
            return
        self.target = group.index
        self.note = f"{'squad' if is_squad else 'farm'} {group.status} hp={group.hp:.0f} rate={rate:.3f}"
        self.comms.claim(group.index)
        self.work(me, group, is_squad)

    def work(self, me, group, is_squad):
        """Fight, capture or approach one group."""
        self.nav.engaged = group.handle
        pos = me.position()
        alive = []
        for camp in visible_camps():
            try:
                if int(camp.camp_group()) == group.handle and camp.is_alive():
                    alive.append(camp)
            except Exception:
                pass
        if alive and is_squad and not any(c.is_awake() for c in alive):
            near = sum(1 for a in vision.champions(Team.ALLY)
                       if a != me and a.is_alive() and a.position().chebyshev_distance(pos) <= 5)
            coming = self.comms.claims().get(group.index, 0)
            if coming and near < min(PARAMS["gather"], coming) and self.world.round - self.commit[1] < 60:
                self.note += " gather"
                self.nav.step(self.approach_goals(me, group))
                return
        if alive:
            # Smith's rule: highest strength per health first.
            from models import CAMP_STATS
            from world import camp_kind
            alive.sort(key=lambda c: -(CAMP_STATS[camp_kind(c)][1] + 1) / max(c.health(), 1))
            in_range = [c for c in alive if me.attack_tiles().is_set(c.position())]
            target = in_range[0] if in_range else alive[0]
            if self.combat.strike(me, target):
                if me.can_move() and me.attack_range() == 1 and not in_range:
                    self.nav.approach(target)
                return
            self.nav.approach(target)
            for camp in alive:
                if self.combat.strike(me, camp):
                    break
            return
        if group.status == "reward" or (group.status == "alive" and self.world.visible(group)):
            if not group.tiles.is_set(pos):
                goals = group.tiles & ~self.nav.blocked()
                if not goals.is_empty():
                    self.nav.step(goals)
            return
        goals = self.approach_goals(me, group)
        if goals.is_set(pos) and group.in_bush:
            near = Bitboard()
            for tile in group.positions:
                near |= ring(tile, 1)
            goals = near & ~self.nav.blocked()
        self.nav.step(goals, dash=True)

    def approach_goals(self, me, group):
        reach = 1 if group.in_bush else max(me.attack_range(), 1)
        goals = Bitboard()
        for tile in group.positions:
            goals |= ring(tile, reach)
        return goals & ~self.nav.blocked()
