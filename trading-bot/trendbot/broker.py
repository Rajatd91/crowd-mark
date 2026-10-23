"""Brokers the runner can talk to.

`PaperBroker` keeps a simulated account in a JSON file and fills every order
at its limit price less costs. It needs no account and is where to start.

`AlpacaBroker` talks to Alpaca's REST API. It uses the paper endpoint unless
both the config (`broker.allow_live = true`) and the command line (`--live`)
say otherwise. Keys come from the environment, never from files in the repo:
APCA_API_KEY_ID and APCA_API_SECRET_KEY.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import requests


@dataclass
class Order:
    symbol: str
    qty: float            # positive buys, negative sells
    limit_price: float
    value: float          # qty * limit_price, signed

    @property
    def side(self) -> str:
        return "buy" if self.qty > 0 else "sell"


@dataclass
class Account:
    equity: float
    cash: float
    last_equity: float | None


class PaperBroker:
    def __init__(self, state_dir: str | Path, initial_cash: float = 10_000.0,
                 commission_per_order: float = 1.0, commission_bps: float = 0.0):
        self.path = Path(state_dir) / "paper_account.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.commission_per_order = commission_per_order
        self.commission_bps = commission_bps
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
        else:
            self.state = {"cash": initial_cash, "positions": {}, "last_equity": None, "fills": []}
            self._save()

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.state, indent=2))

    def positions(self) -> dict[str, float]:
        return {k: v for k, v in self.state["positions"].items() if v}

    def account(self, prices: dict[str, float]) -> Account:
        held = sum(q * prices.get(s, 0.0) for s, q in self.positions().items())
        return Account(self.state["cash"] + held, self.state["cash"], self.state["last_equity"])

    def market_open(self) -> bool:
        return True

    def submit(self, order: Order) -> dict:
        fee = self.commission_per_order + self.commission_bps / 1e4 * abs(order.value)
        cost = order.qty * order.limit_price + fee
        if order.qty > 0 and cost > self.state["cash"] + 1e-9:
            return {"status": "rejected", "reason": "insufficient cash", **asdict(order)}
        held = self.state["positions"].get(order.symbol, 0.0)
        if order.qty < 0 and -order.qty > held + 1e-9:
            return {"status": "rejected", "reason": "cannot sell more than held", **asdict(order)}
        self.state["cash"] -= cost
        self.state["positions"][order.symbol] = held + order.qty
        fill = {"status": "filled", "fee": fee, **asdict(order)}
        self.state["fills"].append(fill)
        self._save()
        return fill

    def mark_close(self, prices: dict[str, float]) -> None:
        """Remember today's equity so tomorrow's daily-loss check has a reference."""
        self.state["last_equity"] = self.account(prices).equity
        self._save()


class AlpacaBroker:
    PAPER = "https://paper-api.alpaca.markets"
    LIVE = "https://api.alpaca.markets"

    def __init__(self, live: bool = False, timeout: float = 15.0):
        key, secret = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
        if not key or not secret:
            raise SystemExit("set APCA_API_KEY_ID and APCA_API_SECRET_KEY in the environment")
        self.base = self.LIVE if live else self.PAPER
        self.live = live
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})

    def _get(self, path: str):
        r = self.session.get(self.base + path, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def positions(self) -> dict[str, float]:
        return {p["symbol"]: float(p["qty"]) for p in self._get("/v2/positions")}

    def account(self, prices: dict[str, float] | None = None) -> Account:
        a = self._get("/v2/account")
        if a.get("trading_blocked") or a.get("account_blocked"):
            raise SystemExit("Alpaca reports this account is blocked from trading")
        return Account(float(a["equity"]), float(a["cash"]), float(a.get("last_equity") or 0) or None)

    def market_open(self) -> bool:
        return bool(self._get("/v2/clock")["is_open"])

    def open_orders(self) -> list[dict]:
        return self._get("/v2/orders?status=open")

    def submit(self, order: Order) -> dict:
        body = {
            "symbol": order.symbol,
            "qty": str(abs(order.qty)),
            "side": order.side,
            "type": "limit",
            "limit_price": f"{order.limit_price:.2f}",
            "time_in_force": "day",
        }
        r = self.session.post(self.base + "/v2/orders", json=body, timeout=self.timeout)
        if r.status_code >= 400:
            return {"status": "rejected", "reason": r.text, **asdict(order)}
        return {"status": "submitted", "broker_id": r.json().get("id"), **asdict(order)}

    def mark_close(self, prices) -> None:
        pass   # Alpaca tracks last_equity itself
