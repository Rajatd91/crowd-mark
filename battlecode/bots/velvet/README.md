# Velvet Wolves: Cambridge Battlecode 2026a bot

Python bot for the CAMBC 2026a game (engine 3.0.0, CLI 5.0.0). The models are
explained, with formulas and backtest evidence, in the
[project README](../../README.md); this page covers how the bot plays.

## How it plays

Every champion runs its own copy of `src/bot.py` and works through the same
order of concerns each turn:

1. **Shop** on spawn, or anywhere for Tavi, buying towards planned emblems.
   Damage dealers go Jungle (30% less camp damage), Monster (15% more camp
   damage), Power, Durability. Tanks start with Jungle Health.
2. **Fight enemy champions** that can reach us. Everyone walks one tile a turn
   and recall breaks on damage, so running rarely works. We focus whichever
   enemy we can kill fastest, casting before attacking and using attack resets.
3. **Survive**: when hurt and no enemy champion is on us, step out of camp
   reach (camps never chase) and recall.
4. **Bank gems** when the bag passes the risk-adjusted threshold `G*`
   (closed form from death hazard, income rate and trip length; see
   `src/models.py`), when the altar is next door, or when the game is about
   to end.
5. **Farm** the camp group with the best gems-per-round rate.

## The maths

- **Rate, not distance.** Each group is scored as
  `value / (travel + kill + capture + extra trips)`, where kill time is the
  group's health divided by damage per round.
- **Smith's rule (scheduling).** Monsters each hit until they die, so total
  damage taken is `sum(strength_i * finish_time_i)`. Killing monsters in
  descending `strength / health` order minimises that sum. This is the classic
  weighted-completion-time result, proved by a swap (exchange) argument over
  permutations of the kill order.
- **Hit-and-run pricing.** If the damage we would soak exceeds our health
  budget, the score adds the round trips home needed to heal, instead of
  refusing the camp.
- **Squad play with death costs.** Big groups (elk, golem, monolith) are taken
  by the whole team. The leader (slot 0) picks the target and writes it to
  shared memory. The plan charges each expected death its 60-round respawn
  plus the walk back.
- **Coordination in 8 bytes.** Bytes 0–6 hold each champion's claimed group;
  byte 7 holds the squad target. On small groups, the lower slot keeps a
  contested claim, which stops teammates flip-flopping.

## Engineering notes

- Pathing treats the reach of awake camps we are not fighting as walls.
- Camps in bushes are invisible from outside, so we walk into the bush.
- A stuck detector drops a target that takes far longer than planned. This
  happens when a hidden enemy contests the capture.
- Knowledge refresh uses native bitboard checks. This cut compute from about
  1.3M to about 0.37M fuel per turn (budget 2.5M), so champions no longer
  stall mid-turn.

## Testing

- `research/tests/test_models.py` unit-tests every model in `src/models.py`
  (for example, Smith's rule against brute force over all permutations).
- `research/arena.py velvet baseline` plays both sides of each map against
  the frozen v4 in `bots/baseline`. `research/stats.py` reports Wilson and
  bootstrap intervals.
- Every number in `src/params.py` came from `research/tune.py` runs on the
  training maps, then was confirmed on held-out maps. See
  `research/results/`.
