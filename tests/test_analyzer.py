import pytest

from core.analyzer import BLOCKS, COL_DRR, COL_STATUS, Status, analyze, classify
from core.parser import COL_CLUSTER, COL_SPEND


def row(res, name):
    r = res.df[res.df[COL_CLUSTER] == name]
    assert len(r) == 1, name
    return r.iloc[0]


def test_drr4_counts(parsed):
    res = analyze(parsed.clusters, price=9500, drr_norm=4)
    assert res.cpo_limit == pytest.approx(380)
    c = {st: t.count for st, t in res.by_status.items()}
    assert c[Status.RED] == 1
    assert c[Status.YELLOW] == 0
    assert c[Status.GREEN] == 13
    assert c[Status.GRAY] == 138
    assert c[Status.NO_SPEND] == 182
    red = res.of_status(Status.RED).iloc[0]
    assert red[COL_CLUSTER] == "косуха женская"
    assert red[COL_SPEND] == pytest.approx(408.90)
    assert res.total_spend == pytest.approx(4532.70, abs=0.01)


def test_drr3_yellow_not_red(parsed):
    res = analyze(parsed.clusters, price=9500, drr_norm=3)
    k = row(res, "кожаная куртка для женщин")
    assert k[COL_STATUS] == Status.YELLOW
    assert k[COL_DRR] == pytest.approx(3.23, abs=0.01)
    assert row(res, "косуха женская")[COL_STATUS] == Status.RED


@pytest.mark.parametrize("drr_norm", [0.1, 1, 3, 4, 10])
def test_clusters_with_orders_never_red(parsed, drr_norm):
    res = analyze(parsed.clusters, price=9500, drr_norm=drr_norm)
    red = res.df[res.df[COL_STATUS] == Status.RED]
    assert (red["Заказанные товары"] == 0).all()


def test_classify_rules():
    # cpo_limit = 380, work_share = 0.5
    assert classify(0, 0, None, 4, 380) == Status.NO_SPEND
    assert classify(380, 0, None, 4, 380) == Status.RED
    assert classify(190, 0, None, 4, 380) == Status.YELLOW
    assert classify(189.99, 0, None, 4, 380) == Status.GRAY
    assert classify(1000, 1, 10.5, 4, 380) == Status.YELLOW
    assert classify(100, 1, 1.05, 4, 380) == Status.GREEN
    assert classify(380, 1, 4.0, 4, 380) == Status.GREEN


def test_sorting(parsed):
    res = analyze(parsed.clusters, price=9500, drr_norm=4)
    d = res.with_spend()
    assert len(d) == 334 - 182
    assert d.iloc[0][COL_STATUS] == Status.RED
    assert d.iloc[-1][COL_STATUS] == Status.GREEN


def test_status_label_renamed():
    assert Status.RED.label == "🔴 Возможно удалить"
    assert all("🔴 Удалить" != s.label for s in Status)


def test_block_totals_drr4(parsed):
    res = analyze(parsed.clusters, price=9500, drr_norm=4)
    bs = res.by_status
    red, yel, gray, green = (bs[s] for s in BLOCKS)
    assert (red.count, red.clicks, red.carts, red.orders) == (1, 94, 5, 0)
    assert red.spend == pytest.approx(408.90) and red.share == pytest.approx(9.02, abs=0.01)
    assert red.cpo is None and red.drr is None, "без заказов CPO и ДРР не считаются"
    assert (yel.count, yel.spend) == (0, 0)
    assert (gray.count, gray.clicks, gray.carts, gray.orders) == (138, 429, 41, 0)
    assert gray.spend == pytest.approx(1866.15) and gray.share == pytest.approx(41.17, abs=0.01)
    assert (green.count, green.clicks, green.carts, green.orders) == (13, 519, 58, 23)
    assert green.spend == pytest.approx(2257.65)
    assert green.cpo == pytest.approx(2257.65 / 23)
    assert green.drr == pytest.approx(2257.65 / (23 * 9500) * 100)
    t = res.total
    assert (t.count, t.clicks, t.carts, t.orders) == (152, 1042, 104, 23)
    assert t.spend == pytest.approx(4532.70) and t.share == pytest.approx(100)
    assert t.cpo == pytest.approx(4532.70 / 23) and t.drr == pytest.approx(2.07, abs=0.01)
    assert t.drr == pytest.approx(res.search_drr)
