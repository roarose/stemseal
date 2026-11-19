from decimal import Decimal, ROUND_FLOOR

def cell_executor(input_data: dict) -> dict:
    """Foreign amount x rate (won per unit), truncated below 1 won. Decimal arithmetic, so 12000 x 9.12 is 109440, not 109439."""
    if 'amount' not in input_data or 'rate' not in input_data:
        raise ValueError("Input must contain 'amount' and 'rate' keys.")
    amount = Decimal(str(input_data['amount']))
    rate = Decimal(str(input_data['rate']))
    if amount < 0 or rate <= 0:
        raise ValueError("Amount must be non-negative and rate must be greater than zero.")
    krw = int((amount * rate).to_integral_value(rounding=ROUND_FLOOR))
    return {"krw": krw}
