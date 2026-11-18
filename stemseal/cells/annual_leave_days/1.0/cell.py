from decimal import Decimal

def cell_executor(input_data: dict) -> dict:
    years = input_data.get('years')
    if not isinstance(years, int) or years < 0:
        raise ValueError("Years must be a non-negative integer.")
    
    # 연차 일수 계산 로직 수정
    leave_days = min(25, 15 + (years - 1) // 2) if years > 0 else 0
    
    return {"leave_days": leave_days}
