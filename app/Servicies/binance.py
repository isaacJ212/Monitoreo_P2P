import httpx
from app.config import settings
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


async def fetch_p2p_ads(
    fiat: str,
    trade_type: str,
    asset: str = "USDT",
    budget: float = 5000.0,
    pay_types: list[str] | None = None,
    rows: int = 15,
    only_merchants: bool | None = None,
) -> list[AdDetail]:

    use_merchants = settings.ONLY_VERIFIED_MERCHANTS if only_merchants is None else only_merchants

    payload = {
        "fiat": fiat.upper(),
        "page": 1,
        "rows": rows,
        "tradeType": trade_type.upper(),
        "asset": asset.upper(),
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

        filtered_ads.append(
            AdDetail(
                adv_no=str(adv.get("advNo", "")),
                price=price,
                min_limit=min_limit,
                max_limit=max_limit,
                suggested_amount_fiat=suggested_fiat,
                suggested_amount_asset=suggested_asset,
                available_asset=available,
                payment_methods=methods,
                merchant_name=advertiser.get("nickName", "Anónimo"),
                month_orders=month_orders,
                finish_rate_pct=round(finish_rate * 100, 2),
                is_verified_merchant=(advertiser.get("userType") == "merchant"),
            )
        )

    return filtered_ads