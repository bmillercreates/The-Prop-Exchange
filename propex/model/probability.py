"""Turn a projection into a probability, and sportsbook prices into fair odds."""

import math

from scipy import stats

# How far real results land from the projection (coefficient of variation).
# Measured by scripts/backtest.py on 2026 weeks 4-7, so it includes both
# normal game-to-game swings and the model's own misses.
CV = {
    ("pass_yds", "QB"): 0.34,
    ("rush_yds", "QB"): 1.10,
    ("rush_yds", "RB"): 0.70,
    ("rush_yds", "WR"): 1.30,
    ("rec_yds", "WR"): 0.77,
    ("rec_yds", "TE"): 0.83,
    ("rec_yds", "RB"): 0.89,
}
RECEPTIONS_DISPERSION = 1.5  # variance / mean for catches (also from the backtest)
# The betting market is sharp. Our final probability leans on it and only
# moves part of the way toward the model, which keeps edges realistic.
MODEL_WEIGHT = 0.35

# Assumed bookmaker margin on one-sided markets (anytime TD only lists "Yes")
TD_MARGIN = 1.07


def american_to_prob(price):
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def american_to_decimal(price):
    return 1 + (price / 100 if price > 0 else 100 / -price)


def decimal_to_american(dec):
    return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))


def no_vig(over_price, under_price):
    """Fair probability of the over once the book's cut is removed."""
    po, pu = american_to_prob(over_price), american_to_prob(under_price)
    return po / (po + pu)


def prob_over(stat, position, mean, line):
    """Chance the player goes over a (usually half-point) line."""
    if mean <= 0:
        return 0.0
    if stat == "receptions":
        # receptions are counts: negative binomial (more spread than Poisson)
        var = mean * RECEPTIONS_DISPERSION
        p = mean / var
        n = mean * p / (1 - p)
        return float(1 - stats.nbinom.cdf(math.floor(line), n, p))
    cv = CV.get((stat, position), 0.7)
    shape = 1 / cv ** 2
    return float(1 - stats.gamma.cdf(line, shape, scale=mean / shape))


def prob_anytime_td(expected_tds):
    return 1 - math.exp(-expected_tds)


def blend_with_market(model_prob, fair_prob):
    return MODEL_WEIGHT * model_prob + (1 - MODEL_WEIGHT) * fair_prob
