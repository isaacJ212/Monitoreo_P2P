from app.Schemas.schemas import AdDetail, ArbitrageMatch, ArbitragePair


def normalize_bank(name: str) -> str:
    n = name.lower()
    if "bac" in n:
        return "BAC Credomatic"
    if "lafise" in n:
        return "Banco LAFISE"
    if "banpro" in n or "billetera" in n:
        return "Banpro (Billetera Móvil)"
    if "transfer" in n or "transferencia" in n:
        return "Transferencia Bancaria"
    return name.strip()


def compute_arbitrage_match(
    buy_ads: list[AdDetail],
    sell_ads: list[AdDetail],
    budget: float = 5000.0,
    fiat: str = "NIO",
    asset: str = "USDT",
) -> ArbitrageMatch | None:
    if not buy_ads or not sell_ads:
        return None

    clean_fiat = fiat.upper()
    clean_asset = asset.upper()
    direct_link = f"https://p2p.binance.com/es/trade/all-payments/{clean_asset}?fiat={clean_fiat}"
    operable_budget = float(budget if budget and budget > 0 else 5000.0)

    # Búsqueda global de todos los cruces con banco coincidente
    valid_pairs: list[ArbitragePair] = []
    seen_pair_keys: set[tuple[str, str, str]] = set()

    for b in buy_ads:
        b_banks_map = {normalize_bank(m): m for m in b.payment_methods}
        for s in sell_ads:
            s_banks_map = {normalize_bank(m): m for m in s.payment_methods}
            common = set(b_banks_map.keys()) & set(s_banks_map.keys())

            if not common:
                continue

            matched_bank = sorted(list(common))[0]
            pair_key = (matched_bank, b.merchant_name, s.merchant_name)
            if pair_key in seen_pair_keys:
                continue
            seen_pair_keys.add(pair_key)

            spread = round(s.price - b.price, 4)
            roi_pct = round((spread / b.price) * 100, 2)
            gain_per_usdt = spread
            gain_per_1000 = round((1000.0 / b.price) * spread, 2)

            usdt_obtained = round(operable_budget / b.price, 2)
            fiat_returned = round(usdt_obtained * s.price, 2)
            net_profit_fiat = round(fiat_returned - operable_budget, 2)
            net_profit_pct = round((net_profit_fiat / operable_budget) * 100, 2)
            within_limits = (b.min_limit <= operable_budget <= b.max_limit) and (s.min_limit <= fiat_returned <= s.max_limit)

            b_link = b.merchant_link or b.link or direct_link
            s_link = s.merchant_link or s.link or direct_link

            valid_pairs.append(
                ArbitragePair(
                    matched_bank=matched_bank,
                    buy_merchant=b.merchant_name,
                    buy_price=b.price,
                    buy_min_limit=b.min_limit,
                    buy_max_limit=b.max_limit,
                    buy_link=b_link,
                    buy_user_no=b.merchant_user_no,
                    buy_merchant_link=b_link,
                    sell_merchant=s.merchant_name,
                    sell_price=s.price,
                    sell_min_limit=s.min_limit,
                    sell_max_limit=s.max_limit,
                    sell_link=s_link,
                    sell_user_no=s.merchant_user_no,
                    sell_merchant_link=s_link,
                    spread=spread,
                    roi_pct=roi_pct,
                    gain_per_usdt=gain_per_usdt,
                    gain_per_1000_fiat=gain_per_1000,
                    simulated_budget=operable_budget,
                    usdt_obtained=usdt_obtained,
                    fiat_returned=fiat_returned,
                    net_profit_fiat=net_profit_fiat,
                    net_profit_pct=net_profit_pct,
                    is_profitable=(spread > 0),
                    is_budget_within_limits=within_limits,
                )
            )

    # Ordenar por mayor ganancia/spread
    valid_pairs.sort(key=lambda p: (p.spread, p.net_profit_fiat), reverse=True)

    # Si hay menos de 3 jugadas del mismo banco, complementar con mejores cruces interbancarios
    if len(valid_pairs) < 3:
        for b in buy_ads:
            b_bank = normalize_bank(b.payment_methods[0]) if b.payment_methods else "BAC Credomatic"
            for s in sell_ads:
                s_bank = normalize_bank(s.payment_methods[0]) if s.payment_methods else "Banpro"
                pair_key = (f"{b_bank} -> {s_bank}", b.merchant_name, s.merchant_name)
                if pair_key in seen_pair_keys:
                    continue
                seen_pair_keys.add(pair_key)

                spread = round(s.price - b.price, 4)
                roi_pct = round((spread / b.price) * 100, 2)
                usdt_obtained = round(operable_budget / b.price, 2)
                fiat_returned = round(usdt_obtained * s.price, 2)
                net_profit_fiat = round(fiat_returned - operable_budget, 2)
                net_profit_pct = round((net_profit_fiat / operable_budget) * 100, 2)
                within_limits = (b.min_limit <= operable_budget <= b.max_limit) and (s.min_limit <= fiat_returned <= s.max_limit)

                b_link = b.merchant_link or b.link or direct_link
                s_link = s.merchant_link or s.link or direct_link

                valid_pairs.append(
                    ArbitragePair(
                        matched_bank=f"{b_bank} ➔ {s_bank}",
                        buy_merchant=b.merchant_name,
                        buy_price=b.price,
                        buy_min_limit=b.min_limit,
                        buy_max_limit=b.max_limit,
                        buy_link=b_link,
                        buy_user_no=b.merchant_user_no,
                        buy_merchant_link=b_link,
                        sell_merchant=s.merchant_name,
                        sell_price=s.price,
                        sell_min_limit=s.min_limit,
                        sell_max_limit=s.max_limit,
                        sell_link=s_link,
                        sell_user_no=s.merchant_user_no,
                        sell_merchant_link=s_link,
                        spread=spread,
                        roi_pct=roi_pct,
                        gain_per_usdt=spread,
                        gain_per_1000_fiat=round((1000.0 / b.price) * spread, 2),
                        simulated_budget=operable_budget,
                        usdt_obtained=usdt_obtained,
                        fiat_returned=fiat_returned,
                        net_profit_fiat=net_profit_fiat,
                        net_profit_pct=net_profit_pct,
                        is_profitable=(spread > 0),
                        is_budget_within_limits=within_limits,
                    )
                )
                if len(valid_pairs) >= 5:
                    break
            if len(valid_pairs) >= 5:
                break

    valid_pairs.sort(key=lambda p: (p.spread, p.net_profit_fiat), reverse=True)

    if valid_pairs:
        winner = valid_pairs[0]
        top_matches = valid_pairs[:3]
        matched_bank = winner.matched_bank

        usdt_obtained = round(operable_budget / winner.buy_price, 2)
        fiat_returned = round(usdt_obtained * winner.sell_price, 2)
        net_profit_fiat = round(fiat_returned - operable_budget, 2)
        net_profit_pct = round((net_profit_fiat / operable_budget) * 100, 2)

        if winner.is_profitable:
            rec = (
                f"🏆 ¡JUGADA GANADORA #1 EN {matched_bank.upper()}! "
                f"Compras a {winner.buy_merchant} (C${winner.buy_price:.2f}) y vendes a {winner.sell_merchant} (C${winner.sell_price:.2f}). "
                f"Con C${operable_budget:,.0f} obtienes {usdt_obtained} USDT y recibes C${fiat_returned:,.2f} NIO. "
                f"Ganancia limpia: +C${net_profit_fiat:,.2f} (+{net_profit_pct}% ROI)."
            )
        else:
            rec = (
                f"La mejor opción con {matched_bank} tiene un diferencial de C${winner.spread:.2f} por USDT. "
                f"El monitor te enviará una alerta automática en cuanto el spread se vuelva positivo."
            )

        return ArbitrageMatch(
            matched_bank=matched_bank,
            buy_merchant=winner.buy_merchant,
            buy_price=winner.buy_price,
            buy_min_limit=winner.buy_min_limit,
            buy_max_limit=winner.buy_max_limit,
            buy_payment_methods=[winner.matched_bank],
            buy_link=winner.buy_link,
            buy_user_no=winner.buy_user_no,
            buy_merchant_link=winner.buy_merchant_link,
            sell_merchant=winner.sell_merchant,
            sell_price=winner.sell_price,
            sell_min_limit=winner.sell_min_limit,
            sell_max_limit=winner.sell_max_limit,
            sell_payment_methods=[winner.matched_bank],
            sell_link=winner.sell_link,
            sell_user_no=winner.sell_user_no,
            sell_merchant_link=winner.sell_merchant_link,
            gross_spread=winner.spread,
            spread_pct=winner.roi_pct,
            simulated_budget=operable_budget,
            usdt_obtained=usdt_obtained,
            fiat_returned=fiat_returned,
            net_profit_fiat=net_profit_fiat,
            net_profit_pct=net_profit_pct,
            gain_per_usdt=winner.gain_per_usdt,
            gain_per_1000_fiat=winner.gain_per_1000_fiat,
            is_profitable=winner.is_profitable,
            is_budget_within_limits=winner.is_budget_within_limits,
            common_payment_methods=[winner.matched_bank],
            recommendation=rec,
            top_matches=top_matches,
        )

    # Fallback si no hay ningún anuncio con banco coincidente
    best_buy = buy_ads[0]
    best_sell = sell_ads[0]
    spread = round(best_sell.price - best_buy.price, 4)
    roi_pct = round((spread / best_buy.price) * 100, 2)
    gain_per_usdt = spread
    gain_per_1000 = round((1000.0 / best_buy.price) * spread, 2)

    usdt_obtained = round(operable_budget / best_buy.price, 2)
    fiat_returned = round(usdt_obtained * best_sell.price, 2)
    net_profit_fiat = round(fiat_returned - operable_budget, 2)
    net_profit_pct = round((net_profit_fiat / operable_budget) * 100, 2)

    within_limits = (best_buy.min_limit <= operable_budget <= best_buy.max_limit) and (best_sell.min_limit <= fiat_returned <= best_sell.max_limit)
    b_link = best_buy.merchant_link or best_buy.link or direct_link
    s_link = best_sell.merchant_link or best_sell.link or direct_link

    fallback_pair = ArbitragePair(
        matched_bank="Distintos Bancos",
        buy_merchant=best_buy.merchant_name,
        buy_price=best_buy.price,
        buy_min_limit=best_buy.min_limit,
        buy_max_limit=best_buy.max_limit,
        buy_link=b_link,
        buy_user_no=best_buy.merchant_user_no,
        buy_merchant_link=b_link,
        sell_merchant=best_sell.merchant_name,
        sell_price=best_sell.price,
        sell_min_limit=best_sell.min_limit,
        sell_max_limit=best_sell.max_limit,
        sell_link=s_link,
        sell_user_no=best_sell.merchant_user_no,
        sell_merchant_link=s_link,
        spread=spread,
        roi_pct=roi_pct,
        gain_per_usdt=gain_per_usdt,
        gain_per_1000_fiat=gain_per_1000,
        simulated_budget=operable_budget,
        usdt_obtained=usdt_obtained,
        fiat_returned=fiat_returned,
        net_profit_fiat=net_profit_fiat,
        net_profit_pct=net_profit_pct,
        is_profitable=(spread > 0),
        is_budget_within_limits=within_limits,
    )

    return ArbitrageMatch(
        matched_bank="Distintos Bancos",
        buy_merchant=best_buy.merchant_name,
        buy_price=best_buy.price,
        buy_min_limit=best_buy.min_limit,
        buy_max_limit=best_buy.max_limit,
        buy_payment_methods=best_buy.payment_methods,
        buy_link=b_link,
        buy_user_no=best_buy.merchant_user_no,
        buy_merchant_link=b_link,
        sell_merchant=best_sell.merchant_name,
        sell_price=best_sell.price,
        sell_min_limit=best_sell.min_limit,
        sell_max_limit=best_sell.max_limit,
        sell_payment_methods=best_sell.payment_methods,
        sell_link=s_link,
        sell_user_no=best_sell.merchant_user_no,
        sell_merchant_link=s_link,
        gross_spread=spread,
        spread_pct=roi_pct,
        simulated_budget=operable_budget,
        usdt_obtained=usdt_obtained,
        fiat_returned=fiat_returned,
        net_profit_fiat=net_profit_fiat,
        net_profit_pct=net_profit_pct,
        gain_per_usdt=gain_per_usdt,
        gain_per_1000_fiat=gain_per_1000,
        is_profitable=(spread > 0),
        is_budget_within_limits=within_limits,
        common_payment_methods=[],
        recommendation="No se detectaron bancos coincidentes entre los anuncios activos. Mostrando mejor cruce interbancario.",
        top_matches=[fallback_pair],
    )
