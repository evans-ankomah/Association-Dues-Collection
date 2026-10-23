from django.core.paginator import Paginator

# Anyone holding one of these may view department-wide dues information.
from apps.common.navigation import FINANCE_VIEWERS

__all__ = ["FINANCE_VIEWERS", "paginate"]


def paginate(request, queryset, per_page=50):
    page = Paginator(queryset, per_page).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return page, query.urlencode()
