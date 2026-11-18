def cell_executor(input_data):
    rates = input_data.get("rates")
    if not isinstance(rates, list) or not rates:
        raise ValueError("rates must be a non-empty list")
    prod = 1.0
    for r in rates:
        f = 1 + float(r)
        if f <= 0:
            raise ValueError("1 + rate must be > 0")
        prod *= f
    return {"geo_mean_pct": round((prod ** (1 / len(rates)) - 1) * 100, 2)}
