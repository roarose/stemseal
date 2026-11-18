def cell_executor(input_data):
    b = input_data.get("before_pct"); a = input_data.get("after_pct")
    if not isinstance(b, (int, float)) or not isinstance(a, (int, float)):
        raise ValueError("before_pct and after_pct must be numbers")
    return {"pp_diff": round(a - b, 2)}
