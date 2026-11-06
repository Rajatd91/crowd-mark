"""Frozen baseline (v4) of the Velvet Wolves bot, kept for A/B backtests: dispatch the draft and champion turns, never letting an error skip end_turn."""
import traceback

import cambc
import draft
from bot import Bot


def main():
    bot = None
    while True:
        try:
            if cambc.is_draft():
                draft.play()
            else:
                if bot is None:
                    bot = Bot()
                bot.play_turn()
        except Exception as error:
            where = traceback.extract_tb(error.__traceback__)[-1]
            print(f"bot error: {error!r} at {where.name}:{where.lineno}", flush=True)
        cambc.end_turn()


if __name__ == "__main__":
    main()
