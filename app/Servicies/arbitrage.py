from app.Schemas.schemas import AdDetail, ArbitrageMatch


def compute_arbitrage_match(
    buy_ads: list[AdDetail],
    sell_ads: list[AdDetail],
    budget: float = 5000.0,
    fiat: str = "NIO",
    asset: str = "USDT",
) -> ArbitrageMatch | None:
    if not buy_ads or not sell_ads:
        return None

    best_buy = buy_ads[0]
    best_sell = sell_ads[0]

    gross_spread = round(best_sell.price - best_buy.price, 4)
    spread_pct = round((gross_spread / best_buy.price) * 100, 2)

    # Simulación de capital
    operable_budget = float(budget if budget > 0 else 5000.0)
    usdt_obtained = round(operable_budget / best_buy.price, 2)
    fiat_returned = round(usdt_obtained * best_sell.price, 2)
    net_profit_fiat = round(fiat_returned - operable_budget, 2)
    net_profit_pct = round((net_profit_fiat / operable_budget) * 100, 2)
    is_profitable = gross_spread > 0

    # Bancos en común entre ambas partes
    buy_methods_set = set(best_buy.payment_methods)
    sell_methods_set = set(best_sell.payment_methods)
    common_methods = list(buy_methods_set & sell_methods_set)

    clean_fiat = fiat.upper()
    if is_profitable:
        rec = (
            f"¡MATCH DE ARBITRAJE RENTABLE! Compras a {best_buy.merchant_name} a C${best_buy.price:.2f} "
            f"y vendes a {best_sell.merchant_name} a C${best_sell.price:.2f}. "
            f"Margen neto: +C${net_profit_fiat:,.2f} (+{net_profit_pct}%) operando C${operable_budget:,.0f} {clean_fiat}."
        )
    else:
        rec = (
            f"Margen regular ({best_buy.price:.2f} compra vs {best_sell.price:.2f} venta). "
            f"El sistema monitorea activamente para avisarte en cuanto el spread se vuelva positivo o toque tus objetivos."
        )

    direct_trade_link = f"https://p2p.binance.com/es/trade/all-payments/{asset.upper()}?fiat={clean_fiat}"

    return ArbitrageMatch(
        buy_merchant=best_buy.merchant_name,
        buy_price=best_buy.price,
        buy_min_limit=best_buy.min_limit,
        buy_max_limit=best_buy.max_limit,
        buy_payment_methods=best_buy.payment_methods,
        buy_link=best_buy.link or direct_trade_link,
        sell_merchant=best_sell.merchant_name,
        sell_price=best_sell.price,
        sell_min_limit=best_sell.min_limit,
        sell_max_limit=best_sell.max_limit,
        sell_payment_methods=best_sell.payment_methods,
        sell_link=best_sell.link or direct_trade_link,
        gross_spread=gross_spread,
        spread_pct=spread_pct,
        simulated_budget=operable_budget,
        usdt_obtained=usdt_obtained,
        fiat_returned=fiat_returned,
        net_profit_fiat=net_profit_fiat,
        net_profit_pct=net_profit_pct,
        is_profitable=is_profitable,
        common_payment_methods=common_methods,
        recommendation=rec,
    )
