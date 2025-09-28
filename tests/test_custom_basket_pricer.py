# Example usage of CustomBasketPricer
import numpy as np
import pandas as pd
import pytest
from app.services.custom_basket_pricer import BasketFees, BasketParameters, CustomBasketPricer

def _create_pricer() -> CustomBasketPricer:
    # Simulated daily prices for 3 symbols over 3 months

    dates = pd.bdate_range("2025-01-01", "2025-03-31")
    prices = pd.DataFrame({
        "AAPL": 180 + np.cumsum(np.random.normal(0, 0.5, len(dates))),
        "MSFT": 400 + np.cumsum(np.random.normal(0, 0.6, len(dates))),
        "TSLA": 250 + np.cumsum(np.random.normal(0, 1.2, len(dates))),
    }, index=dates)

    weights0 = {"AAPL": 0.4, "MSFT": 0.4, "TSLA": 0.2}

    # Taux quotidien ~ 5%/an -> 0.05/252
    funding = pd.Series(0.05/252.0, index=dates)

    params = BasketParameters(
        initial_nav=100.0,
        dividend_yield_ann={"AAPL": 0.005, "MSFT": 0.007, "TSLA": 0.0},
        withholding_by_symbol={"AAPL": 0.15, "MSFT": 0.15}
    )

    fees = BasketFees(
        structuring_fee_bps=5.0,
        exec_cost_bps=2.0,
        default_withholding=0.15,
        borrow_fee_bps={"TSLA": 150.0}  # si short sur TSLA, 150 bps/an
    )

    pricer = CustomBasketPricer(prices, weights0, funding_rate=funding, params=params, fees=fees)
    return pricer

@pytest.mark.skip(reason="Example usage, not a real test")
def test_pricer() -> None:
    pricer = _create_pricer()
    # Calcul initial
    pricer.run()

    # Rebalance médian (par ex. à fin février)
    rebal_date = pd.Timestamp("2025-02-28")
    pricer.rebalance(rebal_date, {"AAPL": 0.33, "MSFT": 0.33, "TSLA": 0.34})
    # (Optionnel) Recalculer ensuite run() si on injecte de nouvelles dates de prix

    res = pricer.results()
    nav = res["nav"]
    pnl = res["pnl_breakdown"]
    wts = res["weights"]

    print(nav.tail())
    print(pnl.tail())
    print(wts.loc[rebal_date])
