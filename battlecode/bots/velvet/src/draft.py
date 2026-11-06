"""Draft: pick champions in a tuned preference order.

Picks never block the opponent (both teams may hold the same champion), so a
fixed preference order is a best response to any opposing draft. The order
is a parameter (params.PARAMS["draft"]), chosen by backtesting candidate
orders against each other (research/tune.py), not by intuition.
"""
import cambc

from params import PARAMS

D = cambc.ChampionDraft
NAMES = {"cassi_issac": D.CASSI_AND_ISSAC, "vendetta": D.VENDETTA, "tavi": D.TAVI, "willow": D.WILLOW,
         "varg": D.VARG, "stellar": D.STELLAR, "ryth": D.RYTH, "marcella": D.MARCELLA, "prism": D.PRISM,
         "vesper_vale": D.VESPER_VALE, "ren": D.REN, "heart_of_ruin": D.HEART_OF_RUIN}


def play():
    chosen = set(int(p) for p in cambc.draft.current_draft(cambc.Team.ALLY))
    order = [NAMES[n] for n in PARAMS["draft"]] + list(NAMES.values())
    for pick in order:
        if int(pick) not in chosen:
            cambc.draft.pick(pick)
            return
