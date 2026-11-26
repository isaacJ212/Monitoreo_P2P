import asyncio
import httpx
from app.config.Config import settings
from app.Schemas.schemas import AdDetail

BINANCE_P2P_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "*/*",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


def _calculate_suggested_amount(min_limit: float, max_limit: float, budget: float) -> float:
    if budget < min_limit:
        return round(min_limit, 2)
    return round(min(budget, max_limit), 2)


_BANK_ALIASES = {
    "bac": ("bac", "credomatic"),
    "banpro": ("banpro", "billetera"),
    "lafise": ("lafise", "bancentro"),
    "bdf": ("bdf", "finanzas"),
    "ficohsa": ("ficohsa",),
    "avanz": ("avanz",),
    "transferencia": ("transfer", "transferencia", "bank transfer"),
}


def normalize_bank_label(raw: str) -> str:
    """Normaliza el nombre de un banco para comparación uniforme."""
    lower = (raw or "").lower()
    if "bac" in lower:
        return "BAC Credomatic"
    if "lafise" in lower or "bancentro" in lower:
        return "Banco LAFISE"
    if "banpro" in lower or "billetera" in lower:
        return "Banpro"
    if "bdf" in lower:
        return "BDF"
    if "ficohsa" in lower:
        return "Ficohsa"
    if "avanz" in lower:
        return "Avanz"
    if "transfer" in lower:
        return "Transferencia Bancaria"
    return (raw or "").strip()


def ad_matches_pay_type(ad: AdDetail, pay_type: str | None) -> bool:
    """Verifica si un anuncio acepta el método de pago configurado por el usuario."""
    if not pay_type or not pay_type.strip():
        return True
    target = pay_type.strip().lower()
    keywords = _BANK_ALIASES.get(target, (target,))
    for method in ad.payment_methods:
        m_lower = method.lower()
        if any(k in m_lower for k in keywords) or normalize_bank_label(method).lower() == target:
            return True
    return False


def filter_ads_by_config(
    ads: list[AdDetail],
    budget: float | None = None,
    pay_types: list[str] | None = None,
    only_merchants: bool = False,
) -> tuple[list[AdDetail], bool]:
    """
    Filtra anuncios según banco, comerciantes verificados y presupuesto.
    Retorna (anuncios_filtrados, se_filtro_por_presupuesto).
    """
    result = ads
    if only_merchants:
        result = [a for a in result if a.is_verified_merchant]

    if pay_types:
        clean_pts = [p.strip() for p in pay_types if p and p.strip()]
        if clean_pts:
            result = [a for a in result if any(ad_matches_pay_type(a, pt) for pt in clean_pts)]

    budget_applied = False
    if budget and budget > 0:
        within_budget = [a for a in result if a.min_limit <= budget <= a.max_limit]
        if within_budget:
            result = within_budget
            budget_applied = True

    return result, budget_applied


async def fetch_p2p_ads(
    fiat: str,
    trade_type: str,
    asset: str = "USDT",
    budget: float = 5000.0,
    pay_types: list[str] | None = None,
    rows: int = 20,
    only_merchants: bool | None = None,
    page: int = 1,
) -> list[AdDetail]:
    use_merchants = settings.ONLY_VERIFIED_MERCHANTS if only_merchants is None else only_merchants
    clean_fiat = fiat.upper()
    clean_asset = asset.upper()
    clean_trade = trade_type.upper()

    payload = {
        "fiat": clean_fiat,
        "page": page,
        "rows": rows,
        "tradeType": clean_trade,
        "asset": clean_asset,
        "countries": [],
        "proMerchantAds": False,
        "shieldMerchantAds": False,
        "publisherType": "merchant" if use_merchants else None,
        "payTypes": pay_types or [],
        "classifies": ["mass", "profession", "fiat_trade"],
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(BINANCE_P2P_URL, json=payload, headers=HEADERS)
        response.raise_for_status()
        body = response.json()

    raw_ads = body.get("data") or []
    filtered_ads: list[AdDetail] = []

    for item in raw_ads:
        adv = item.get("adv", {})
        advertiser = item.get("advertiser", {})

        finish_rate = float(advertiser.get("monthFinishRate") or 0.0)
        month_orders = int(advertiser.get("monthOrderCount") or 0)

        if finish_rate < settings.MIN_FINISH_RATE or month_orders < settings.MIN_MONTH_ORDERS:
            continue

        price = float(adv.get("price", 0))
        if price <= 0:
            continue

        min_limit = float(adv.get("minSingleTransAmount", 0))
        max_limit = float(adv.get("maxSingleTransAmount", 0))
        available = float(adv.get("surplusAmount", 0))

        methods = [
            m.get("tradeMethodName") or m.get("identifier") or "Desconocido"
            for m in adv.get("tradeMethods", [])
        ]

        suggested_fiat = _calculate_suggested_amount(min_limit, max_limit, budget)
        suggested_asset = round(suggested_fiat / price, 2)
        adv_no = str(adv.get("advNo", ""))
        user_no = str(advertiser.get("userNo", ""))
        merchant_link = (
            f"https://p2p.binance.com/es/advertiserDetail?userNo={user_no}"
            if user_no
            else f"https://p2p.binance.com/es/trade/{clean_trade.lower()}/{clean_asset}?fiat={clean_fiat}"
        )

        filtered_ads.append(
            AdDetail(
                adv_no=adv_no,
                price=price,
                min_limit=min_limit,
                max_limit=max_limit,
                suggested_amount_fiat=suggested_fiat,
                suggested_amount_asset=suggested_asset,
                available_asset=available,
                payment_methods=methods,
                merchant_name=advertiser.get("nickName", "Anónimo"),
                merchant_user_no=user_no,
                merchant_link=merchant_link,
                month_orders=month_orders,
                finish_rate_pct=round(finish_rate * 100, 2),
                is_verified_merchant=(advertiser.get("userType") == "merchant"),
                link=merchant_link,
            )
        )

    # Ordenamiento estricto en tiempo real:
    # Para COMPRA (BUY): El usuario busca el precio más barato (ascendente)
    # Para VENTA (SELL): El usuario busca el precio más alto (descendente)
    if clean_trade == "BUY":
        filtered_ads.sort(key=lambda a: a.price)
    else:
        filtered_ads.sort(key=lambda a: a.price, reverse=True)

    return filtered_ads


async def fetch_p2p_market_depth(
    fiat: str,
    trade_type: str,
    asset: str = "USDT",
    budget: float = 5000.0,
    only_merchants: bool | None = None,
    pages: int = 2,
) -> list[AdDetail]:
    """Obtiene múltiples páginas del mercado general P2P sin filtro de banco para poder
    mostrar tanto el panorama general como el filtrado preciso por banco y presupuesto."""
    tasks = [
        fetch_p2p_ads(
            fiat=fiat,
            trade_type=trade_type,
            asset=asset,
            budget=budget,
            pay_types=[],
            rows=20,
            only_merchants=only_merchants,
            page=p,
        )
        for p in range(1, pages + 1)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    merged: list[AdDetail] = []
    seen_adv: set[str] = set()
    for res in results:
        if isinstance(res, Exception) or not res:
            continue
        for ad in res:
            key = ad.adv_no or f"{ad.merchant_name}:{ad.price}"
            if key not in seen_adv:
                seen_adv.add(key)
                merged.append(ad)

    if trade_type.upper() == "BUY":
        merged.sort(key=lambda a: a.price)
    else:
        merged.sort(key=lambda a: a.price, reverse=True)

    return merged
