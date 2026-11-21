def cell_executor(inp):
    extra = sorted(str(k) for k in inp if k not in ("sets", "people"))
    if extra:
        raise ValueError("unknown input %s; use sets, people" % extra[:3])
    sets = inp.get("sets")
    if not isinstance(sets, list) or not sets or not all(isinstance(x, dict) and isinstance(x.get("name"), str) and isinstance(x.get("people"), int) and not isinstance(x.get("price"), bool) and isinstance(x.get("price"), int) for x in sets):
        raise ValueError("pass sets: the store's list [{name, people (whole number), price (whole won)}] from the store's data")
    n = inp.get("people")
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("pass people: how many, a whole number 1 or more (read it with the people step first)")
    fit = [{"name": x["name"], "price": x["price"]} for x in sets if x["people"] == n]
    if not fit:
        return {"answer_ready": False, "asks": ["%d분께 딱 맞는 세트는 없어요. 직원이 메뉴를 맞춰 드릴게요." % n], "sets": []}
    return {"answer_ready": True, "asks": [], "sets": fit}
