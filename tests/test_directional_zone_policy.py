from price_action.zones import calculate_zones, unavailable_zones


def test_buy_location_accepts_full_discount_half():
    deep_discount = calculate_zones(110.0, 100.0, 102.0)
    preferred_pullback = calculate_zones(110.0, 100.0, 104.5)

    assert deep_discount.location == "DISCOUNT"
    assert deep_discount.valid_for_direction("BUY")
    assert preferred_pullback.location == "BULLISH_PULLBACK"
    assert preferred_pullback.valid_for_direction("BUY")
    assert not deep_discount.valid_for_direction("SELL")


def test_sell_location_accepts_full_premium_half():
    deep_premium = calculate_zones(110.0, 100.0, 108.0)
    preferred_pullback = calculate_zones(110.0, 100.0, 105.5)

    assert deep_premium.location == "PREMIUM"
    assert deep_premium.valid_for_direction("SELL")
    assert preferred_pullback.location == "BEARISH_PULLBACK"
    assert preferred_pullback.valid_for_direction("SELL")
    assert not deep_premium.valid_for_direction("BUY")


def test_equilibrium_and_unavailable_ranges_fail_closed():
    equilibrium = calculate_zones(110.0, 100.0, 105.0)
    unavailable = unavailable_zones()
    crossed = calculate_zones(100.0, 110.0, 105.0)

    assert equilibrium.location == "EQUILIBRIUM"
    assert not equilibrium.valid_for_direction("BUY")
    assert not equilibrium.valid_for_direction("SELL")
    assert not unavailable.valid_for_direction("BUY")
    assert not unavailable.valid_for_direction("SELL")
    assert crossed.location == "UNAVAILABLE"
    assert not crossed.valid_for_direction("BUY")
    assert not crossed.valid_for_direction("SELL")
