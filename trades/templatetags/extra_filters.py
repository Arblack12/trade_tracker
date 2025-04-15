# trades/templatetags/extra_filters.py

from django import template
from decimal import Decimal, InvalidOperation # Use Decimal for precision

register = template.Library()

@register.filter(name='divide')
def divide(value, arg):
    """
    Divides the value by the argument. Returns None on error.
    Uses Decimal for precision suitable for currency.
    """
    try:
        # Attempt to convert inputs to Decimal
        value = Decimal(value)
        arg = Decimal(arg)

        # Handle division by zero
        if arg == 0:
            return None  # Or perhaps return an empty string '' or 0

        # Perform division
        return value / arg
    except (TypeError, ValueError, InvalidOperation, ZeroDivisionError):
        # Handle cases where conversion fails or other math errors
        return None # Return None if inputs are not valid numbers

@register.filter(name='multiply')
def multiply(value, arg):
    """
    Multiplies the value by the argument. Returns None on error.
    Uses Decimal for precision.
    """
    try:
        # Attempt to convert inputs to Decimal
        value = Decimal(value)
        arg = Decimal(arg)

        # Perform multiplication
        return value * arg
    except (TypeError, ValueError, InvalidOperation):
         # Handle cases where conversion fails
         return None

# +++ ADDED FILTER +++
@register.filter(name='subtract')
def subtract(value, arg):
    """
    Subtracts the arg from the value. Returns None on error.
    Uses Decimal for precision.
    """
    try:
        value = Decimal(str(value)) # Convert to string first for robustness
        arg = Decimal(str(arg))     # Convert to string first for robustness
        return value - arg
    except (TypeError, ValueError, InvalidOperation):
        return None
# +++ END ADDED FILTER +++

# Optional: A filter to handle None values before other formatting
@register.filter(name='default_if_none')
def default_if_none(value, default_value=""):
    """
    Returns the default_value if the input value is None.
    Useful for chaining filters where an error might return None.
    Example: {{ result|default_if_none:0|floatformat:2 }}
    """
    if value is None:
        return default_value
    return value