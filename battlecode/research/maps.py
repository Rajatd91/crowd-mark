"""Train/test split of the published map pool.

Tournaments are played on unseen maps, so parameters are tuned on the
training maps only and judged on held-out test maps, the backtesting
equivalent of in-sample against out-of-sample. The split is a deterministic
hash of the map name: stable across runs and independent of map order.
"""
import hashlib
import os

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def all_maps():
    return sorted(f for f in os.listdir(os.path.join(WS, "maps")) if f.endswith(".map26a"))


def bucket(name):
    return int(hashlib.sha256(name.encode()).hexdigest(), 16) % 10


def split(which):
    maps = all_maps()
    if which == "all":
        return maps
    if which == "train":
        return [m for m in maps if bucket(m) < 6]
    if which == "test":
        return [m for m in maps if bucket(m) >= 6]
    if which == "train_quick":
        return [m for m in maps if bucket(m) < 6][::3]
    if which == "quick":
        return [m for m in maps if bucket(m) >= 6][::3]
    raise ValueError(which)


if __name__ == "__main__":
    for which in ("train", "test", "quick"):
        print(which, len(split(which)))
