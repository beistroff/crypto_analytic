from sentinel.signals.btc_regime import classify


def test_regime_labels():
    # Above both averages (+2) and up 4% in 7 days (+1): risk on.
    assert classify(82000, 0.5, 4.0, 80000, 75000).regime == "risk_on"
    # Below both (-2) and down 2.5% today (-1): risk off.
    assert classify(70000, -2.5, -1.0, 80000, 75000).regime == "risk_off"
    # Below SMA50 (-1), SMA200 missing (0), down 6% in 7 days (-1): neutral.
    regime = classify(78000, 0.1, -6.0, 80000, None, dominance=58.1)
    assert (regime.regime, regime.points, regime.dominance) == ("neutral", -2, 58.1)
