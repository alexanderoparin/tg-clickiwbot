import pytest

from bot.validators import InputError, parse_drr, parse_label, parse_price


@pytest.mark.parametrize("text,value", [
    ("9500", 9500), ("9 500", 9500), ("9500,50", 9500.5), ("9 500 ₽", 9500),
    ("1", 1), ("10000000", 10_000_000), ("12 345.678", 12345.68), ("9500 руб", 9500),
])
def test_price_ok(text, value):
    assert parse_price(text) == value


@pytest.mark.parametrize("text", ["", "abc", "0", "0,5", "-5", "10000001", "9.500.00", "1e5"])
def test_price_bad(text):
    with pytest.raises(InputError):
        parse_price(text)


@pytest.mark.parametrize("text,value", [("4", 4), ("4,5", 4.5), ("4.5%", 4.5), ("0,1", 0.1), ("100", 100)])
def test_drr_ok(text, value):
    assert parse_drr(text) == value


@pytest.mark.parametrize("text", ["0", "0,05", "101", "пять", ""])
def test_drr_bad(text):
    with pytest.raises(InputError):
        parse_drr(text)


def test_label():
    assert parse_label("  ИП  Иванов ") == "ИП Иванов"
    assert len(parse_label("x" * 200)) == 64
    with pytest.raises(InputError):
        parse_label("   ")
