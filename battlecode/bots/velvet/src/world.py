"""Map knowledge and team communication.

`World` holds static map facts (built once) and a belief state for every camp
group: alive with an estimated health, reward waiting, or respawning with an
expected return round. Vision is per champion, so each bot keeps its own
beliefs; the team shares only what fits in 8 bytes of shared memory (`Comms`).
"""
import cambc
from cambc import game_map, vision, Team
from cambc import constants as K

from models import CAMP_STATS

Bitboard, DistanceField = cambc.Bitboard, cambc.DistanceField
UNREACHABLE = 60000


def camp_kind(camp):
    for name in ("gem_cluster", "gold_cluster", "wolf", "elk", "golem", "monolith"):
        if getattr(camp, "is_" + name)():
            return name
    return "wolf"


def ring(center, radius):
    tiles = Bitboard()
    tiles.draw_chebyshev(center, radius)
    return tiles


def visible_camps():
    """Visible camps, tolerating a camp leaving vision mid-turn."""
    try:
        return vision.camps()
    except Exception:
        out = []
        for tile in vision.camp_tiles().positions():
            try:
                out.append(vision.camp_at(tile))
            except Exception:
                pass
        return out


def single(position):
    tiles = Bitboard()
    tiles.set(position, True)
    return tiles


class Group:
    """One camp group: static facts plus this champion's belief about it."""

    def __init__(self, index, group, bushes):
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
        self.monsters = [(CAMP_STATS[k][1], CAMP_STATS[k][0]) for k in kinds]
        self.in_bush = not (self.tiles & bushes).is_empty()
        self.home_distance = UNREACHABLE
        # Belief state.
        self.status = "alive"         # "alive" | "reward" | "respawn"
        self.ready_at = 0
        self.hp = self.max_hp


class World:
    """Static map caches and the group belief state."""

    def __init__(self):
        self.terrain = (game_map.walls() | game_map.holes() | game_map.altars()
                        | game_map.spawn_region(Team.ENEMY))
        self.home = game_map.spawn_region(Team.ALLY)
        self.bushes = game_map.bushes()
        self.altars = game_map.altars().positions()
        self.altar_ring = Bitboard()
        for altar in self.altars:
            self.altar_ring |= ring(altar, K.SUBMIT_GEMS_RANGE)
        self.groups = [Group(i, g, self.bushes) for i, g in enumerate(game_map.camp_groups())]
        self.by_handle = {g.handle: g for g in self.groups}
        home_field = DistanceField()
        home_field.compute(self.terrain, self.home, Bitboard(), UNREACHABLE)
        self.home_field = home_field
        for g in self.groups:
            g.home_distance = min([home_field.get(p) for p in g.positions] or [UNREACHABLE])
        self.round = 0
        self.field = None             # distances from this champion, rebuilt each turn

    def refresh(self, position):
        self.round = cambc.round_number()
        self.field = DistanceField()
        self.field.compute(self.terrain, single(position), Bitboard(), UNREACHABLE)
        self.observe()

    def observe(self):
        """Update beliefs from vision with native bitboard checks.

        Monsters never leave their spawn tile, so a visible spawn tile with no
        camp on it means that monster is dead. Only a fully visible, empty
        group needs the engine's state query to tell reward from respawning.
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
                continue
            try:
                state = g.ref.state()
            except Exception:
                continue
            if isinstance(state, game_map.CampGroupRespawning):
                g.status, g.ready_at, g.hp = "respawn", self.round + int(state.timer), g.max_hp
            elif isinstance(state, game_map.CampGroupRewardAvailable):
                g.status, g.hp = "reward", 0

    def distance_to(self, group):
        best = UNREACHABLE
        for tile in group.positions:
            d = self.field.get(tile)
            if d < best:
                best = d
        return best

    def altar_distance(self):
        best = UNREACHABLE
        for tile in self.altar_ring.positions():
            d = self.field.get(tile)
            if d < best:
                best = d
        return best

    def visible(self, group):
        return not (group.tiles & vision.visible_tiles()).is_empty()


class Comms:
    """8 bytes of team memory.

    Bytes 0..6: the group each champion slot has claimed (index + 1, 0 = none).
    Byte 7: the squad target the leader (slot 0) has chosen.
    """
    SQUAD = 7

    def __init__(self, me):
        allies = cambc.champions(Team.ALLY)
        self.team_size = max(len(allies), 1)
        self.slot = 0
        for i, champion in enumerate(allies):
            if champion == me:
                self.slot = min(i, self.SQUAD - 1)
        self.below = set()

    def _read(self):
        data = bytearray(K.SHARED_MEMORY_BYTES)
        try:
            cambc.shared_memory.read(0, data)
        except Exception:
            pass
        return data

    def claims(self):
        """Group index -> teammates claiming it; records groups held by lower slots."""
        out = {}
        self.below = set()
        for i, value in enumerate(self._read()[:self.SQUAD]):
            if i != self.slot and value:
                out[value - 1] = out.get(value - 1, 0) + 1
                if i < self.slot:
                    self.below.add(value - 1)
        return out

    def claim(self, index):
        self._write(self.slot, 0 if index is None else (index % 255) + 1)

    def squad(self, groups):
        value = self._read()[self.SQUAD]
        return groups[value - 1] if value and value - 1 < len(groups) else None

    def set_squad(self, group):
        self._write(self.SQUAD, 0 if group is None else group.index + 1)

    def _write(self, offset, value):
        try:
            cambc.shared_memory.write(offset, bytes([value]))
        except Exception:
            pass
