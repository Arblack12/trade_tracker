# trades/templatetags/query_transform.py
from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def query_transform(context, **kwargs):
    """
    Updates the current request's GET parameters with provided kwargs,
    preserving existing ones.

    Usage in template:
    <a href="?{% query_transform request key1='value1' key2=some_var %}">Link</a>
    <a href="{{ base_url }}?{% query_transform request page=page_obj.next_page_number %}">
    """
    query = context['request'].GET.copy()
    for k, v in kwargs.items():
        query[k] = v
    return query.urlencode()