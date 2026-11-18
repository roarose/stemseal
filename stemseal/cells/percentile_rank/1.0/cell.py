from collections import Counter
from decimal import Decimal
from fractions import Fraction
from functools import reduce
from itertools import filterfalse
import json
import math
import re
import statistics

def cell_executor(input_data: dict) -> dict:
    if not isinstance(input_data.get("values"), list) or not all(isinstance(x, (int, float)) for x in input_data["values"]):
        raise ValueError("Invalid 'values' input: must be a list of numbers.")
    if not isinstance(input_data.get("value"), (int, float)):
        raise ValueError("Invalid 'value' input: must be a number.")
    if not input_data["values"]:
        raise ValueError("Input list 'values' cannot be empty.")
    
    values = input_data["values"]
    value = input_data["value"]
    
    # Filter values smaller than 'value'
    smaller_count = sum(1 for v in values if v < value)
    
    # Calculate percentile rank
    percentile_rank = round((smaller_count / len(values)) * 100, 2)
    
    return {"percentile_rank": percentile_rank}
