from decimal import Decimal

def cell_executor(input_data: dict) -> dict:
    if 'hourly_wage' not in input_data or input_data['hourly_wage'] <= 0:
        raise ValueError("hourly_wage must be greater than 0")
    
    hourly_wage = Decimal(input_data['hourly_wage'])
    hours = input_data.get('hours', Decimal(209))
    
    if not isinstance(hours, Decimal) and not isinstance(hours, int):
        raise ValueError("hours must be an integer or Decimal")
    
    if not isinstance(hours, Decimal):
        hours = Decimal(hours)
    
    monthly_wage = hourly_wage * hours
    return {"monthly_wage": int(monthly_wage.quantize(Decimal('0.01')))}
