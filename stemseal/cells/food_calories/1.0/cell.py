def cell_executor(input_data):
    k = input_data.get("kcal_per_100g"); g = input_data.get("grams")
    if not isinstance(k, (int, float)) or not isinstance(g, (int, float)) or k < 0 or g < 0:
        raise ValueError("kcal_per_100g and grams must be numbers >= 0")
    return {"kcal": round(k * g / 100, 1)}
