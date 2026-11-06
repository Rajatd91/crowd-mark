"""Movement: shortest paths over a per-turn occupancy map, with danger avoidance.

Blocked tiles (terrain plus visible units) are computed once per turn. The
reach of awake camps we are not deliberately fighting is treated as a wall,
unless that leaves no route or we already stand inside it: camps never chase,
but they hit anything in range.
"""
import cambc
from cambc import vision

from world import UNREACHABLE, ring, single, visible_camps

Bitboard, DistanceField = cambc.Bitboard, cambc.DistanceField


class Navigator:
    def __init__(self, world):
        self.world = world
        self.engaged = None           # handle of the group we are fighting this turn
        self.threat_zone = Bitboard() # enemy reach we would rather not enter
        self._blocked = None

    def new_turn(self, me):
        self.me = me
        self.engaged = None
        self.threat_zone = Bitboard()
        self._blocked = None

    def blocked(self):
        if self._blocked is None:
            blocked = self.world.terrain.copy()
            for source in (vision.champion_tiles, vision.camp_tiles, vision.teleport_tiles):
                try:
                    blocked |= source()
                except Exception:
                    pass
            try:
                blocked.set(self.me.position(), False)
            except Exception:
                pass
            self._blocked = blocked
        return self._blocked.copy()

    def danger(self):
        zone = self.threat_zone.copy()
        for camp in visible_camps():
            try:
                if camp.is_awake() and int(camp.camp_group()) != self.engaged:
                    zone |= ring(camp.position(), camp.attack_range())
            except Exception:
                pass
        return zone

    def step(self, goals, dash=False):
        """One walking step along a shortest path to the nearest goal, then an optional dash."""
        me = self.me
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
            here = field.get(origin)
            options = [p for p in reachable.positions() if field.get(p) < here]
            if options:
                try:
                    moved = bool(me.move_absolute(min(options, key=field.get)))
                except Exception:
                    moved = False
                if moved:
                    self._blocked = None
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
                                self._blocked = None
                            break
                    except Exception:
                        continue
        return moved

    def approach(self, target, reach=None):
        """Move to within attack reach of a visible unit."""
        me = self.me
        if not me.can_move():
            return False
        try:
            if not target.is_visible():
                return False
            goals = ring(target.position(), reach or me.attack_range()) & ~self.blocked()
        except Exception:
            return False
        return self.step(goals)

    def home(self):
        return self.step(self.world.home.copy())
