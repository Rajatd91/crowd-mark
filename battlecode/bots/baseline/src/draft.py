"""Draft: pick champions in a fixed order of camp-farming strength.

Picks never block the opponent (both teams may hold the same champion), so the
best response to any opposing draft is simply our own preference order. The
order ranks sustained damage against camps, survivability and utility:

- Cassi & Issac: one pick, two bodies, so two attacks a turn.
- Vendetta: highest base strength and growth; camp kills reset her cooldowns.
- Tavi: buys shards anywhere, so his power grows without trips home.
- Willow: heals allies for 3x Focus and hits hard at range.
- Varg: splash attacks clear grouped camps; self-shield.
"""
import cambc

D = cambc.ChampionDraft
ORDER = (D.CASSI_AND_ISSAC, D.VENDETTA, D.TAVI, D.WILLOW, D.VARG, D.STELLAR,
         D.RYTH, D.MARCELLA, D.PRISM, D.VESPER_VALE, D.REN, D.HEART_OF_RUIN)


def play():
    chosen = set(int(p) for p in cambc.draft.current_draft(cambc.Team.ALLY))
    for pick in ORDER:
        if int(pick) not in chosen:
            cambc.draft.pick(pick)
            return
