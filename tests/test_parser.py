from datetime import date
from io import BytesIO

import pandas as pd
import pytest

from core.parser import COL_SPEND, ParseError, parse_file, parse_period


def test_clusters_count(parsed):
    assert len(parsed.clusters) == 334


def test_period(parsed):
    assert parsed.period_from == date(2026, 9, 17)
    assert parsed.period_to == date(2026, 9, 23)


def test_total_spend(parsed):
    assert parsed.clusters[COL_SPEND].sum() == pytest.approx(4532.70, abs=0.01)


def test_no_warnings_on_fixture(parsed):
    # лист words_cluster больше не читается и предупреждений не даёт
    assert parsed.warnings == []
    assert not hasattr(parsed, "words")


def test_period_variants():
    assert parse_period("Топ_поисковых_кластеров_2026-09-17_-_2026-09-23.xlsx") == (
        date(2026, 9, 17), date(2026, 9, 23))
    assert parse_period("Топ поисковых кластеров 2026-09-17 - 2026-09-23.xlsx") == (
        date(2026, 9, 17), date(2026, 9, 23))
    assert parse_period("export.xlsx") == (None, None)


def test_not_excel():
    with pytest.raises(ParseError, match="не Excel"):
        parse_file(b"not an excel file at all", filename="report.xlsx")
    with pytest.raises(ParseError, match="не Excel"):
        parse_file(b"a,b,c", filename="report.csv")


def _xlsx(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
    return buf.getvalue()


def test_missing_columns():
    data = _xlsx({"Топ поисковых кластеров": pd.DataFrame(
        {"Кластер": ["a"], "Затраты": [1], "Клики": [3]})})
    with pytest.raises(ParseError) as e:
        parse_file(data, filename="x.xlsx")
    msg = str(e.value)
    assert "Добавления в корзину" in msg and "Заказанные товары" in msg
    assert "Клики" not in msg


def test_sheet_found_by_columns():
    df = pd.DataFrame({
        "Кластер": [" a ", "a", "b", None],
        "Клики": [10, 5, "", 1],
        "Добавления в корзину": [1, 0, 0, 0],
        "Заказанные товары": [0, 1, 0, 0],
        "Затраты": ["1 000,50", 2, None, 0],
        "Валюта": ["USD", "USD", "USD", "USD"],
    })
    p = parse_file(_xlsx({"Лист1": pd.DataFrame({"x": [1]}), "Данные": df}), filename="x.xlsx")
    assert p.period_from is None
    assert list(p.clusters["Кластер"]) == ["a", "b"]
    a = p.clusters.iloc[0]
    assert a["Затраты"] == pytest.approx(1002.5)
    assert a["Клики"] == 15 and a["Заказанные товары"] == 1
    assert p.clusters.iloc[1]["Затраты"] == 0
    assert p.warnings == ["⚠️ Валюта в файле не RUB: USD"]


def test_too_many_rows():
    df = pd.DataFrame({"Кластер": [f"k{i}" for i in range(11)], "Клики": 1,
                       "Добавления в корзину": 0, "Заказанные товары": 0, "Затраты": 1})
    data = _xlsx({"Топ поисковых кластеров": df})
    assert len(parse_file(data, filename="x.xlsx", max_rows=11).clusters) == 11
    with pytest.raises(ParseError, match="11 строк .* лимита 10"):
        parse_file(data, filename="x.xlsx", max_rows=10)


def test_too_big_file(fixture_path):
    with pytest.raises(ParseError, match="больше 0 МБ"):
        parse_file(fixture_path, max_size=1000)
    with pytest.raises(ParseError, match="больше 10 МБ"):
        parse_file(b"x" * (10 * 1024 * 1024 + 1), filename="x.xlsx")
