# tennis/templatetags/tennis_extras.py
from django import template

register = template.Library()

@register.filter
def dict_get(d, key):
    try:
        return d.get(key, False)
    except Exception:
        return False

@register.filter(name="get_item")
def get_item(d, key):
    try:
        return d.get(key)
    except Exception:
        return None