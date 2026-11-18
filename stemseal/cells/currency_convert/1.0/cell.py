from math import floor

def cell_executor(input_data: dict) -> dict:
    if 'amount' not in input_data or 'rate' not in input_data:
        raise ValueError("Input must contain 'amount' and 'rate' keys.")
    
    amount = input_data['amount']
    rate = input_data['rate']
    
    if amount < 0 or rate <= 0:
        raise ValueError("Amount must be non-negative and rate must be greater than zero.")
    
    krw = floor(amount * rate)
    return {"krw": krw}
