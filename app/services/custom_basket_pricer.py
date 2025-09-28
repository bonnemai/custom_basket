from __future__ import annotations
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass
class BasketFees:
    structuring_fee_bps: float = 0.0        # annuel, ex: 5 => 5 bps/an
    exec_cost_bps: float = 0.0              # par rebalance, appliqué au turnover du panier
    default_withholding: float = 0.0        # ex: 0.15 => 15% de retenue
    borrow_fee_bps: Dict[str, float] = field(default_factory=dict)  # par symbole et par an (si short)

@dataclass
class BasketParameters:
    initial_nav: float = 100.0
    initial_notional: float = 1_000_000.0   # notionnel de référence (pour coûts absolus si besoin)
    dividend_yield_ann: Dict[str, float] = field(default_factory=dict)  # ex: {"AAPL": 0.005}
    withholding_by_symbol: Dict[str, float] = field(default_factory=dict)  # prioritaire sur default_withholding

class CustomBasketPricer:
    """
    Delta-one custom basket pricer
    --------------------------------
    Inputs:
      - prices: DataFrame [dates x symbols] (prix de clôture)
      - weights0: dict symbol->poids initial (somme ~ 1.0; shorts négatifs autorisés)
      - funding_rate: Series quotidienne (taux/jour, ex SOFR+spread / 252)
         -> ex: funding_rate = (SOFR_daily + spread_daily)
         -> sinon, un float quotidien constant (ex: 0.0002 ~ 5%/an / 252)
      - params: BasketParameters
      - fees: BasketFees

    Sorties:
      - nav: Series NAV
      - pnl_breakdown: DataFrame (Price, Dividend, Funding, Borrow, Structuring, RebalanceCost)
      - weights: DataFrame des poids à travers le temps (post-rebals)
    """
    def __init__(
        self,
        prices: pd.DataFrame,
        weights0: Dict[str, float],
        funding_rate: pd.Series | float = 0.0,
        params: Optional[BasketParameters] = None,
        fees: Optional[BasketFees] = None,
    ):
        self.prices = prices.sort_index()
        self.symbols = list(prices.columns)
        self._check_weights(weights0)

        self.weights = pd.DataFrame(index=self.prices.index, columns=self.symbols, dtype=float)
        self.weights.iloc[0] = self._normalize(pd.Series(weights0, index=self.symbols).fillna(0.0))

        self.params = params or BasketParameters()
        self.fees = fees or BasketFees()

        # funding rate to daily float series
        if isinstance(funding_rate, pd.Series):
            self.funding_rate = funding_rate.reindex(self.prices.index).fillna(method="ffill").fillna(0.0)
        else:
            self.funding_rate = pd.Series(funding_rate, index=self.prices.index, dtype=float)

        self.nav = pd.Series(index=self.prices.index, dtype=float)
        self.nav.iloc[0] = self.params.initial_nav

        self.pnl_breakdown = pd.DataFrame(
            0.0, index=self.prices.index,
            columns=["Price", "Dividend", "Funding", "Borrow", "Structuring", "RebalanceCost"]
        )

    # ---------- Helpers ----------
    def _check_weights(self, w: Dict[str, float]):
        extra = set(w.keys()) - set(self.symbols)
        if extra:
            raise ValueError(f"Unknown symbols in weights: {extra}")

    @staticmethod
    def _normalize(w: pd.Series) -> pd.Series:
        s = w.sum()
        return w if np.isclose(s, 1.0) else (w / s if s != 0 else w)

    # ---------- Mechanics ----------
    def _dividend_daily(self, date, prev_date, w_prev) -> float:
        """Approximation dividendes: yield annuel * prix * dt ; retenue à la source ; converti en PnL NAV."""
        if prev_date is None:
            return 0.0
        dt = self._dt(prev_date, date)
        dy = pd.Series({s: self.params.dividend_yield_ann.get(s, 0.0) for s in self.symbols})
        wh = pd.Series({s: self.params.withholding_by_symbol.get(s, self.fees.default_withholding) for s in self.symbols})

        # Valeur du panier à t-1 (NAV * poids)
        basket_val_prev = self.nav.loc[prev_date]
        position_val_prev = w_prev * basket_val_prev

        # Dividendes bruts ~ rendement * valeur exposée * dt
        gross = (dy * position_val_prev.abs()) * dt
        net = gross * (1.0 - wh)
        # Longs perçoivent, shorts paient (approx. scrip/comp) -> signe = signe du poids
        signed = net * np.sign(w_prev)
        return signed.sum()

    def _funding_daily(self, date, prev_date) -> float:
        """Financing sur le notionnel du panier (NAV) à t-1."""
        if prev_date is None:
            return 0.0
        dt_rate = self.funding_rate.loc[date]  # déjà quotidien
        basket_val_prev = self.nav.loc[prev_date]
        return - basket_val_prev * dt_rate  # coût => signe négatif

    def _borrow_daily(self, date, prev_date, w_prev) -> float:
        """Borrow fee pour shorts (bps/an ⇒ quotidien), appliqué sur la valeur short à t-1."""
        if prev_date is None:
            return 0.0
        dt = self._dt(prev_date, date)
        basket_val_prev = self.nav.loc[prev_date]
        short_val = (w_prev.clip(upper=0.0).abs()) * basket_val_prev
        # par symbole si dispo, sinon 0
        bps = pd.Series({s: self.fees.borrow_fee_bps.get(s, 0.0) for s in self.symbols}) / 10_000.0
        return - (short_val * (bps * (252*dt))).sum()

    def _structuring_daily(self, date, prev_date) -> float:
        """Structuring fee en bps/an => quotidien sur NAV t-1."""
        if prev_date is None:
            return 0.0
        dt = self._dt(prev_date, date)
        basket_val_prev = self.nav.loc[prev_date]
        return - basket_val_prev * (self.fees.structuring_fee_bps / 10_000.0) * (252 * dt)

    def _price_pnl(self, date, prev_date, w_prev) -> float:
        """PnL prix = somme(weight_{t-1} * return sous-jacent * NAV_{t-1})."""
        if prev_date is None:
            return 0.0
        basket_val_prev = self.nav.loc[prev_date]
        r = (self.prices.loc[date] / self.prices.loc[prev_date] - 1.0).fillna(0.0)
        return (w_prev * r * basket_val_prev).sum()

    @staticmethod
    def _dt(prev_date, date) -> float:
        # dt ~ 1 jour de bourse => 1/252 ; si calendrier irrégulier, on peut raffiner via jours réels/365
        return 1.0 / 252.0

    # ---------- Public API ----------
    def run(self) -> None:
        """Calcule NAV et PnL breakdown sans rebalancements supplémentaires."""
        prev_date = None
        for date in self.prices.index:
            if prev_date is None:
                prev_date = date
                continue

            w_prev = self.weights.loc[prev_date].fillna(0.0)

            price_pnl = self._price_pnl(date, prev_date, w_prev)
            div_pnl = self._dividend_daily(date, prev_date, w_prev)
            fund_pnl = self._funding_daily(date, prev_date)
            borr_pnl = self._borrow_daily(date, prev_date, w_prev)
            struct_pnl = self._structuring_daily(date, prev_date)

            total = price_pnl + div_pnl + fund_pnl + borr_pnl + struct_pnl
            self.pnl_breakdown.loc[date, ["Price", "Dividend", "Funding", "Borrow", "Structuring"]] = \
                [price_pnl, div_pnl, fund_pnl, borr_pnl, struct_pnl]

            self.nav.loc[date] = self.nav.loc[prev_date] + total

            # Poids driftent avec les prix (pas de rebalance automatique)
            # Valeurs par ligne à t : V_i(t) = w_prev_i * NAV_{t-1} * (P_i(t)/P_i(t-1))
            line_vals_t = w_prev * self.nav.loc[prev_date] * (self.prices.loc[date] / self.prices.loc[prev_date]).fillna(1.0)
            self.weights.loc[date] = (line_vals_t / line_vals_t.sum()).fillna(0.0)

            prev_date = date

    def rebalance(self, date, target_weights: Dict[str, float]) -> None:
        """
        Rebalance aux poids cibles (normalisés) à 'date'.
        Coût d'exécution = exec_cost_bps * turnover_notional.
        """
        if date not in self.prices.index:
            raise ValueError("Rebalance date must be in prices index")

        tw = self._normalize(pd.Series(target_weights, index=self.symbols).fillna(0.0))
        self.weights.loc[date] = tw

        # turnover = 0.5 * somme(|Δw|) * NAV (approx, en valeur absolue totale échangée)
        prev_date = self.prices.index[self.prices.index.get_loc(date) - 1] if self.prices.index.get_loc(date) > 0 else None
        if prev_date is None:
            return

        w_prev = self.weights.loc[prev_date].fillna(0.0)
        turnover = (tw - w_prev).abs().sum() * 0.5 * self.nav.loc[prev_date]
        cost = - turnover * (self.fees.exec_cost_bps / 10_000.0)
        # Applique le coût sur la NAV le jour du rebalance
        self.nav.loc[date] = (self.nav.loc[date] if pd.notna(self.nav.loc[date]) else self.nav.loc[prev_date]) + cost
        self.pnl_breakdown.loc[date, "RebalanceCost"] += cost

    def results(self) -> dict:
        out = {
            "nav": self.nav.copy(),
            "pnl_breakdown": self.pnl_breakdown.copy(),
            "weights": self.weights.copy(),
        }
        return out
