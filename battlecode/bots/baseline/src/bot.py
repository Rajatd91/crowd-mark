"""Champion decisions for the Velvet Wolves bot.

Each champion runs its own copy of this code. Every turn it works through a
fixed order of concerns: shop, survive, fight enemies it can beat, bank gems,
then farm the camp group with the best gems-per-round rate.

The farming choice is a rate, not a distance: value / (travel + kill + capture),
where kill time is the group's health over this champion's damage per round.
Within a group, monsters are killed in Smith's-rule order (highest strength
per health first), which minimises the total damage the group deals while it
dies.
"""
import cambc
from cambc import game_map, vision, Team
from cambc import constants as K

Bitboard, DistanceField, Vec2 = cambc.Bitboard, cambc.DistanceField, cambc.Vec2
F, S, CT = cambc.ItemFamily, cambc.ItemStat, cambc.ChampionType

# Camp table from the handbook (finals patch): health, strength, attack range.
CAMP_STATS = {
    "wolf": (1350, 20, 3), "elk": (2400, 60, 4), "golem": (5000, 120, 4),
    "monolith": (20000, 200, 5), "gem_cluster": (120, 0, 0), "gold_cluster": (120, 0, 0),
}
UNREACHABLE = 60000
GOLD_WEIGHT = 0.12          # gems one gold is worth, early; it fades towards the end
CLAIM_SMALL_HP = 1600       # groups below this are worth one champion only
SQUAD_BYTE = 7              # shared-memory byte holding the squad's group (index + 1)
TEAM_DPS_EACH = 70.0        # rough camp damage per champion, for squad planning
TEAM_HP_EACH = 900.0        # rough health per champion, for squad planning
GATHER = 2                  # allies needed nearby before the squad wakes a big group

# Emblem plans: (family, stat, how many emblems of it we want in total).
STRENGTH_BUILD = [(F.JUNGLE, S.STRENGTH, 1), (F.MONSTER, S.STRENGTH, 1), (F.POWER, S.STRENGTH, 1),
                  (F.DURABILITY, S.HEALTH, 1), (F.POWER, S.STRENGTH, 2), (F.POWER, S.HEALTH, 1),
                  (F.POWER, S.STRENGTH, 3), (F.POWER, S.STRENGTH, 4), (F.POWER, S.STRENGTH, 6)]
TANK_BUILD = [(F.JUNGLE, S.HEALTH, 1), (F.MONSTER, S.STRENGTH, 1), (F.DURABILITY, S.HEALTH, 1),
              (F.POWER, S.STRENGTH, 1), (F.POWER, S.HEALTH, 1), (F.POWER, S.STRENGTH, 2),
              (F.POWER, S.HEALTH, 2), (F.POWER, S.STRENGTH, 4)]
TANKS = (CT.RYTH, CT.MARCELLA)


def camp_kind(camp):
    for name in ("gem_cluster", "gold_cluster", "wolf", "elk", "golem", "monolith"):
        if getattr(camp, "is_" + name)():
            return name
    return "wolf"


def chebyshev_ring(center, radius):
    tiles = Bitboard()
    tiles.draw_chebyshev(center, radius)
    return tiles


def single(position):
    tiles = Bitboard()
    tiles.set(position, True)
    return tiles


class Group:
    """Static facts about one camp group, read once from the map."""

    def __init__(self, index, group):
        self.index = index
        self.handle = int(group)
        self.ref = group
        self.tiles = group.spawn_tiles()
        self.positions = self.tiles.positions()
        self.gems = group.gem_value()
        self.gold = group.gold_value()
        self.respawn = group.max_respawn_timer()
        camps = group.camps()
        kinds = [camp_kind(c) for c in camps]
        self.tile_hp = {c.spawn_position(): CAMP_STATS[k][0] for c, k in zip(camps, kinds)}
        self.max_hp = sum(CAMP_STATS[k][0] for k in kinds)
        self.strength = sum(CAMP_STATS[k][1] for k in kinds)
        self.reach = max(CAMP_STATS[k][2] for k in kinds)
        stats = [(CAMP_STATS[k][1], CAMP_STATS[k][0]) for k in kinds]
        self.monsters = sorted(stats, key=lambda m: -m[0] / m[1])
        self.home_distance = UNREACHABLE
        self.in_bush = not (self.tiles & game_map.bushes()).is_empty()
        # Knowledge: "alive", "reward" or a respawn round; all groups start alive.
        self.status = "alive"
        self.ready_at = 0
        self.hp = self.max_hp


class Bot:
    def __init__(self):
        me = cambc.me()
        self.kind = int(me.champion_name())
        self.kind_name = str(me.champion_name())
        self.build = TANK_BUILD if self.kind in [int(t) for t in TANKS] else STRENGTH_BUILD
        self.is_tavi = self.kind == int(CT.TAVI)
        self.terrain = (game_map.walls() | game_map.holes() | game_map.altars()
                        | game_map.spawn_region(Team.ENEMY))
        self.home = game_map.spawn_region(Team.ALLY)
        self.altars = game_map.altars().positions()
        self.bushes = game_map.bushes()
        self.groups = [Group(i, g) for i, g in enumerate(game_map.camp_groups())]
        self.by_handle = {g.handle: g for g in self.groups}
        home_field = DistanceField()
        home_field.compute(self.terrain, self.home, Bitboard(), UNREACHABLE)
        for g in self.groups:
            g.home_distance = min([home_field.get(p) for p in g.positions] or [UNREACHABLE])
        self.slot = None
        self.target = None          # group index we are working on
        self.engaged = None         # handle of the group we are fighting this turn
        self.commit = None          # (group index, round we committed, rounds we expected)
        self.banned = {}            # group index -> round until which we leave it alone
        self.field = None

    # ------------------------------------------------------------------ turn
    def play_turn(self):
        self.note = "-"
        try:
            self.decide()
        finally:
            if self.round % 40 == 0:
                me = self.me
                try:
                    where = me.position() if me.is_alive() else "dead"
                    print(f"r{self.round} {self.kind_name} {where} hp={me.health():.0f}/{me.max_health():.0f} "
                          f"gems={me.gem_count()} gold={me.gold_count()} tgt={self.target} {self.note}", flush=True)
                except Exception as error:
                    print(f"status: {error!r}", flush=True)

    def decide(self):
        me = cambc.me()
        self.me = me
        self.round = cambc.round_number()
        if self.slot is None:
            self.slot = self.find_slot(me)

        if not me.is_alive():
            self.shop(me)               # the dead may still shop
            self.claim(None)
            return
        if me.is_recalling() or me.is_teleporting() or me.is_submitting_gems():
            return
        self.observe()
        self.engaged = None
        pos = me.position()
        at_home = self.home.is_set(pos)
        if at_home or self.is_tavi:
            self.shop(me)

        self.field = DistanceField()
        self.field.compute(self.terrain, single(pos), Bitboard(), UNREACHABLE)

        enemies = [c for c in vision.champions(Team.ENEMY) if c.is_alive() and c.is_visible()]
        threats = self.threats(me, enemies)

        # Heal up fully at home before heading out again.
        if at_home and me.health() < 0.9 * me.max_health() and not threats:
            self.claim(None)
            return
        if self.fight_enemies(me, enemies):
            self.note = "pvp"
            return
        if self.survive(me, threats, at_home):
            self.note = "survive"
            return
        if self.should_bank(me, enemies):
            if self.bank(me):
                self.note = "bank"
                return
        if self.should_go_shopping(me, threats, at_home):
            me.recall()
            return
        self.farm(me)

    # ------------------------------------------------------------- knowledge
    def find_slot(self, me):
        allies = cambc.champions(Team.ALLY)
        self.team_size = max(len(allies), 1)
        for i, champion in enumerate(allies):
            if champion == me:
                return min(i, SQUAD_BYTE - 1)
        return 0

    def observe(self):
        """Refresh group status from vision using native bitboard checks.

        Monsters never leave their spawn tile, so a visible spawn tile without a
        camp on it means that monster is dead. Only fully empty groups need the
        (more expensive) engine state query to tell reward from respawning.
        """
        seen = vision.visible_tiles()
        occupied = vision.camp_tiles()
        for g in self.groups:
            if g.status == "respawn" and self.round >= g.ready_at:
                g.status, g.hp = "alive", g.max_hp
            visible = g.tiles & seen
            if visible.is_empty():
                continue
            living = g.tiles & occupied
            if not living.is_empty():
                g.status = "alive"
                hp = 0.0
                for tile in living.positions():
                    try:
                        hp += vision.camp_at(tile).health()
                    except Exception:
                        hp += g.tile_hp.get(tile, 0)
                for tile in (g.tiles & ~seen).positions():
                    hp += g.tile_hp.get(tile, 0)
                g.hp = hp
                continue
            if visible != g.tiles:
                continue                      # part of the group is hidden: keep what we knew
            try:
                state = g.ref.state()
            except Exception:
                continue
            if isinstance(state, game_map.CampGroupRespawning):
                g.status = "respawn"
                g.ready_at = self.round + int(state.timer)
                g.hp = g.max_hp
            elif isinstance(state, game_map.CampGroupRewardAvailable):
                g.status, g.hp = "reward", 0

    def memory(self):
        data = bytearray(K.SHARED_MEMORY_BYTES)
        try:
            cambc.shared_memory.read(0, data)
        except Exception:
            pass
        return data

    def claims(self):
        """Group index -> number of teammates claiming it."""
        out = {}
        self.claimed_below = set()      # groups claimed by a teammate in a lower slot
        for i, value in enumerate(self.memory()[:SQUAD_BYTE]):
            if i != self.slot and value:
                out[value - 1] = out.get(value - 1, 0) + 1
                if i < self.slot:
                    self.claimed_below.add(value - 1)
        return out

    def squad_target(self):
        value = self.memory()[SQUAD_BYTE]
        if value and value - 1 < len(self.groups):
            return self.groups[value - 1]
        return None

    def set_squad_target(self, group):
        try:
            cambc.shared_memory.write(SQUAD_BYTE, bytes([0 if group is None else group.index + 1]))
        except Exception:
            pass

    def claim(self, index):
        try:
            cambc.shared_memory.write(self.slot, bytes([0 if index is None else (index % 255) + 1]))
        except Exception:
            pass

    # ---------------------------------------------------------------- combat
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

    def threats(self, me, enemies):
        """Enemies and awake camps that can hit us where we stand."""
        pos = me.position()
        out = [e for e in enemies if pos.chebyshev_distance(e.position()) <= max(e.attack_range(), 4) + 1]
        for camp in vision.camps():
            try:
                if camp.is_awake() and pos.chebyshev_distance(camp.position()) <= camp.attack_range():
                    out.append(camp)
            except Exception:
                pass
        return out

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

    def fight_enemies(self, me, enemies):
        """Champion combat.

        Fleeing rarely works (everyone walks one tile a turn and recall breaks on
        damage), so once an enemy can reach us we fight, focusing whichever enemy
        we can kill fastest. Out of reach, we only chase enemies we can kill.
        """
        if not enemies:
            return False
        pos = me.position()
        my_dps = max(me.strength(), 1.0)
        burst = self.burst(me)
        engaged, chase = [], []
        for enemy in enemies:
            try:
                epos = enemy.position()
                e_hp = enemy.health()
                distance = pos.chebyshev_distance(epos)
                threat_range = max(enemy.attack_range(), 4 if enemy.attack_range() > 1 else 2)
            except Exception:
                continue
            ttk = max(0.0, e_hp - burst) / my_dps
            if distance <= max(me.attack_range(), threat_range):
                engaged.append((ttk, e_hp, enemy))
            elif e_hp <= burst * 1.2 and distance <= me.attack_range() + 2:
                chase.append((ttk, e_hp, enemy))
        pool = engaged or chase
        if not pool:
            return False
        pool.sort(key=lambda t: (t[0], t[1]))
        target = pool[0][2]
        if self.strike(me, target):
            if me.can_move() and me.attack_range() == 1:
                self.approach(me, target)
            return True
        if me.can_move():
            self.approach(me, target)
            self.strike(me, target)
        return True

    def strike(self, me, target):
        """Cast, attack and reset against one unit. Returns True if anything happened."""
        acted = False
        try:
            if me.can_cast() and self.cast_offensive(me, target):
                acted = True
            if me.can_attack() and me.attack_tiles().is_set(target.position()) and target.health() > 0:
                me.attack(target)
                acted = True
                if me.can_cast():
                    for ability in me.abilities():
                        if ability.is_ready() and ability.is_attack_reset():
                            if ability.use():
                                if me.can_attack() and target.is_visible() and target.health() > 0:
                                    me.attack(target)
                            break
        except Exception as error:
            print(f"strike: {error!r}", flush=True)
        return acted

    def cast_offensive(self, me, target):
        tpos = target.position()
        harmless = isinstance(target, cambc.Camp) and CAMP_STATS[camp_kind(target)][1] == 0
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
                unit_ok = (ability.can_target_camps() if isinstance(target, cambc.Camp)
                           else ability.can_target_enemies())
                if unit_ok and ability.use(target):
                    return True
                if not unit_ok and ability.can_target_ground() and ability.use(tpos):
                    return True
            except Exception:
                continue
        return False

    def support(self, me, threats):
        """Heal the most wounded ally, or shield ourselves under fire."""
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
                if ability.is_shield() and threats and me.health() < 0.85 * me.max_health():
                    if ability.use():
                        return True
            except Exception:
                continue
        return False

    # --------------------------------------------------------------- survival
    def survive(self, me, threats, at_home):
        """Retreat or recall when hurt. Returns True if the turn is spent."""
        self.support(me, threats)
        low = me.health() < 0.38 * me.max_health()
        if not low or at_home:
            return False
        if any(not isinstance(t, cambc.Camp) for t in threats):
            return False                      # an enemy champion is on us: keep fighting
        if not threats:
            me.recall()
            return True
        # Camps never chase: stepping out of their reach lets us recall safely.
        if me.can_move():
            self.step_towards(me, self.home.copy())
        return True

    def should_go_shopping(self, me, threats, at_home):
        if at_home or threats or self.is_tavi or me.gem_count() > 0:
            return False
        gold = me.gold_count()
        if self.round > K.MAX_ROUNDS - 250:
            return False
        return gold >= 300 or (gold >= 150 and me.health() < 0.6 * me.max_health())

    # ---------------------------------------------------------------- banking
    def altar_distance(self):
        best = (UNREACHABLE, None)
        for altar in self.altars:
            for tile in chebyshev_ring(altar, K.SUBMIT_GEMS_RANGE).positions():
                d = self.field.get(tile)
                if d < best[0]:
                    best = (d, altar)
        return best

    def should_bank(self, me, enemies):
        gems = me.gem_count()
        if gems <= 0:
            return False
        distance, _ = self.altar_distance()
        if distance >= UNREACHABLE:
            return False
        left = K.MAX_ROUNDS - self.round
        if left < distance + gems // 10 + 25:
            return True
        if enemies and gems >= 8:
            return True
        if gems >= 36:
            return True
        return gems >= 14 and distance <= 10

    def bank(self, me):
        pos = me.position()
        for altar in self.altars:
            if pos.chebyshev_distance(altar) <= K.SUBMIT_GEMS_RANGE:
                try:
                    me.submit_gems(altar)
                    self.claim(None)
                    return True
                except Exception as error:
                    print(f"submit: {error!r}", flush=True)
        if not me.can_move():
            return True
        goals = Bitboard()
        for altar in self.altars:
            goals |= chebyshev_ring(altar, K.SUBMIT_GEMS_RANGE)
        goals &= ~self.blocked()
        moved = self.step_towards(me, goals, dash=True)
        pos = me.position()
        for altar in self.altars:
            if pos.chebyshev_distance(altar) <= K.SUBMIT_GEMS_RANGE:
                try:
                    me.submit_gems(altar)
                except Exception:
                    pass
                break
        return moved or True

    # ---------------------------------------------------------------- farming
    def group_distance(self, group):
        best = UNREACHABLE
        for tile in group.positions:
            d = self.field.get(tile)
            if d < best:
                best = d
        return best

    def score(self, me, group, distance, dps, claims):
        """Gems-per-round rate of committing to this group, with hit-and-run trips priced in."""
        if distance >= UNREACHABLE or self.banned.get(group.index, 0) > self.round:
            return None
        wait = 0
        if group.status == "respawn":
            wait = max(0, group.ready_at - self.round - distance)
            if wait > 30:
                return None
        helpers = claims.get(group.index, 0)
        hp = 0 if group.status == "reward" else group.hp
        if hp < CLAIM_SMALL_HP and group.index in self.claimed_below:
            return None                       # a lower slot has it; it keeps it
        if hp < CLAIM_SMALL_HP:
            helpers = 0
        team_dps = dps * (1 + 0.8 * helpers)
        kill = hp / team_dps
        soak = 0.0
        if hp > 0:
            # Smith's rule order; each monster hits until it dies, shared among attackers.
            clock = 0.0
            scale = hp / max(group.max_hp, 1)
            for strength, health in group.monsters:
                clock += health * scale / team_dps
                soak += strength * clock
            soak /= (1 + helpers)
            if self.has_emblem(me, F.JUNGLE):
                soak *= 0.7
        budget = 0.6 * me.max_health()
        trips = 0
        if soak > 0.6 * me.health():
            trips = int((soak - 0.6 * me.health()) / budget) + 1
        if trips > 3:
            return None
        trip_cost = 2 * group.home_distance + 12
        late = max(0.0, 1.0 - self.round / (K.MAX_ROUNDS * 0.8))
        value = group.gems + GOLD_WEIGHT * late * group.gold
        if value <= 0:
            return None
        if hp >= CLAIM_SMALL_HP and helpers:
            value *= 1.15                     # join a big camp a teammate is already on
        rounds = distance + kill + K.CAPTURE_TIME + wait + trips * trip_cost + 3
        return value / rounds

    def has_emblem(self, me, family):
        try:
            counts = me.item_count()
            return any(counts[int(cambc.get_item_enum(family, stat, False))] for stat in (S.STRENGTH, S.HEALTH, S.FOCUS))
        except Exception:
            return False

    def farm(self, me):
        dps = self.camp_dps(me)
        claims = self.claims()
        best = None
        for group in self.groups:
            if group.hp >= CLAIM_SMALL_HP and group.status != "reward":
                continue                      # big groups are squad business
            s = self.score(me, group, self.group_distance(group), dps, claims)
            if s is not None and self.commit is not None and self.commit[0] == group.index:
                s *= 1.3                      # stickiness: finish what we started
            if s is not None and (best is None or s > best[0]):
                best = (s, group, False)
        squad = self.plan_squad(me) if self.slot == 0 else self.squad_target()
        if squad is not None and squad.status != "respawn" and self.banned.get(squad.index, 0) <= self.round:
            rate = self.squad_rate(me, squad)
            if rate is not None and (best is None or rate > best[0]):
                best = (rate, squad, True)
        if best is None:
            self.note = "idle"
            self.target = None
            self.claim(None)
            if me.gem_count() > 0:
                self.bank(me)
            elif me.can_move():
                self.step_towards(me, self.home.copy())
            return
        group = best[1]
        if self.commit is None or self.commit[0] != group.index:
            expected = 1.0 / max(best[0], 1e-3) * (group.gems / (self.team_size if best[2] else 1) + 1)
            self.commit = (group.index, self.round, min(400, expected * 1.6 + 30))
        elif self.round - self.commit[1] > self.commit[2]:
            # Far slower than planned: something we cannot see is blocking us.
            self.banned[group.index] = self.round + 80
            self.commit = None
            self.note = "stuck"
            return
        self.target = group.index
        self.note = f"{'squad' if best[2] else 'farm'} {group.status} hp={group.hp:.0f} rate={best[0]:.3f}"
        self.claim(group.index)
        self.work_group(me, group, squad=best[2])

    def squad_cost(self, group, distance):
        """Rounds for the whole team to clear and capture a big group, deaths included.

        Monsters hit the nearest champion until they die, so the team soaks the
        Smith's-rule damage total. Health beyond the team's pool turns into
        deaths, and each death costs a 60-round respawn plus the walk back.
        """
        team_dps = TEAM_DPS_EACH * self.team_size
        kill = group.hp / team_dps
        clock = soak = 0.0
        scale = group.hp / max(group.max_hp, 1)
        for strength, health in group.monsters:
            clock += health * scale / team_dps
            soak += strength * clock
        pool = 0.7 * TEAM_HP_EACH * self.team_size
        deaths = max(0.0, (soak - pool) / TEAM_HP_EACH)
        downtime = deaths * (K.RESPAWN_TIME + group.home_distance) / self.team_size
        return distance + kill + K.CAPTURE_TIME + 8 + downtime

    def plan_squad(self, me):
        """Leader only: choose the big group the whole team should take next."""
        current = self.squad_target()
        if current is not None and current.status == "alive" and current.hp < current.max_hp:
            return current                    # finish what we started
        if current is not None and current.status != "respawn" and self.round % 8:
            return current                    # replanning is costly; do it every few rounds
        best = None
        for group in self.groups:
            if group.max_hp < CLAIM_SMALL_HP or group.status == "respawn":
                continue
            distance = self.group_distance(group)
            if distance >= UNREACHABLE:
                continue
            rate = group.gems / self.squad_cost(group, distance)
            if best is None or rate > best[0]:
                best = (rate, group)
        target = best[1] if best else None
        self.set_squad_target(target)
        return target

    def squad_rate(self, me, group):
        distance = self.group_distance(group)
        if distance >= UNREACHABLE:
            return None
        return group.gems / self.team_size / self.squad_cost(group, distance) * 1.3

    def work_group(self, me, group, squad=False):
        self.engaged = group.handle
        pos = me.position()
        alive = []
        for camp in vision.camps():
            try:
                if int(camp.camp_group()) == group.handle and camp.is_alive():
                    alive.append(camp)
            except Exception:
                pass
        if alive and squad and not any(c.is_awake() for c in alive):
            near = sum(1 for a in vision.champions(Team.ALLY)
                       if a != me and a.is_alive() and a.position().chebyshev_distance(pos) <= 5)
            coming = self.claims().get(group.index, 0)
            if coming and near < min(GATHER, coming) and self.round - self.commit[1] < 60:
                self.note += " gather"
                reach = max(me.attack_range(), 1)
                goals = Bitboard()
                for tile in group.positions:
                    goals |= chebyshev_ring(tile, reach)
                goals &= ~self.blocked()
                self.step_towards(me, goals)
                return
        if alive:
            # Smith's rule: kill the highest strength-per-health monster first.
            alive.sort(key=lambda c: -(CAMP_STATS[camp_kind(c)][1] + 1) / max(c.health(), 1))
            in_range = [c for c in alive if me.attack_tiles().is_set(c.position())]
            target = in_range[0] if in_range else alive[0]
            if self.strike(me, target):
                if me.can_move() and me.attack_range() == 1 and not in_range:
                    self.approach(me, target)
                return
            self.approach(me, target)
            for camp in alive:
                if self.strike(me, camp):
                    break
            return
        if group.status == "reward" or group.status == "alive" and self.round > 0 and self.visible(group):
            # Cleared: stand on a free spawn tile until the capture completes.
            if group.tiles.is_set(pos):
                return
            goals = group.tiles & ~self.blocked()
            if not goals.is_empty():
                self.step_towards(me, goals)
            return
        # Not in sight yet: travel towards the group. Camps inside a bush are
        # invisible from outside it, so for those we walk into the bush itself.
        goals = self.approach_goals(me, group)
        if goals.is_set(pos) and group.in_bush:
            near = Bitboard()
            for tile in group.positions:
                near |= chebyshev_ring(tile, 1)
            goals = near & ~self.blocked()
        self.step_towards(me, goals, dash=True)

    def approach_goals(self, me, group):
        reach = max(me.attack_range(), 1)
        goals = Bitboard()
        for tile in group.positions:
            goals |= chebyshev_ring(tile, 1 if group.in_bush else reach)
        if group.in_bush:
            goals = (goals & self.bushes) | goals
        return goals & ~self.blocked()

    def visible(self, group):
        seen = vision.visible_tiles()
        return not (group.tiles & seen).is_empty()

    def approach(self, me, target):
        if not me.can_move():
            return
        try:
            if not target.is_visible():
                return
            goals = chebyshev_ring(target.position(), me.attack_range()) & ~self.blocked()
        except Exception:
            return
        self.step_towards(me, goals)

    # --------------------------------------------------------------- movement
    def blocked(self):
        blocked = self.terrain.copy()
        for source in (vision.champion_tiles, vision.camp_tiles, vision.teleport_tiles):
            try:
                blocked |= source()
            except Exception:
                pass
        blocked.set(self.me.position(), False)
        return blocked

    def danger(self):
        """Tiles inside the reach of awake camps we are not deliberately fighting."""
        zone = Bitboard()
        for camp in vision.camps():
            try:
                if camp.is_awake() and int(camp.camp_group()) != self.engaged:
                    zone |= chebyshev_ring(camp.position(), camp.attack_range())
            except Exception:
                pass
        return zone

    def step_towards(self, me, goals, dash=False):
        """Walk one step along a shortest path to the nearest goal tile, then dash if allowed.

        Awake camps never chase but hit anything in reach, so their reach is
        treated as a wall unless we are already standing inside it.
        """
        origin = me.position()
        if goals.is_empty() or goals.is_set(origin):
            return False
        blocked = self.blocked()
        zone = self.danger()
        if not zone.is_set(origin):
            avoid = blocked | (zone & ~goals)
            probe = DistanceField()
            probe.compute_to(avoid & ~goals, goals, single(origin), Bitboard())
            if probe.get(origin) < UNREACHABLE:
                blocked = avoid
        field = DistanceField()
        field.compute_to(blocked & ~goals, goals, single(origin), Bitboard())
        moved = False
        if me.can_move():
            reachable = blocked.reachable_tiles(origin, me.base_stats().base_move_speed)
            options = [p for p in reachable.positions() if field.get(p) < field.get(origin)]
            if options:
                step = min(options, key=field.get)
                try:
                    moved = bool(me.move_absolute(step))
                except Exception:
                    moved = False
        if dash and me.can_cast():
            here = me.position()
            if field.get(here) > 3:
                for ability in me.abilities():
                    try:
                        if ability.is_ready() and ability.is_dash() and not ability.is_damage():
                            tiles = ability.valid_tiles() & ~self.blocked()
                            options = [p for p in tiles.positions() if field.get(p) < field.get(here) - 1]
                            if options and ability.use(min(options, key=field.get)):
                                moved = True
                            break
                    except Exception:
                        continue
        return moved

    # --------------------------------------------------------------- shopping
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
                if n <= 0:
                    return
                if not me.can_buy(shard, n):
                    return
                me.buy(shard, n)
                gold -= n * cost
                if n < need:
                    return
                counts = me.item_count()
        except Exception as error:
            print(f"shop: {error!r}", flush=True)
