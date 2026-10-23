"""Sidebar navigation. Each item is shown only when the user holds one of its permissions
in the current department (None means any signed-in user)."""

from dataclasses import dataclass

from django.urls import NoReverseMatch, reverse


@dataclass(frozen=True)
class NavItem:
    label: str
    url_name: str
    permissions: tuple[str, ...] | None = None
    platform_admin_only: bool = False


NAV_SECTIONS: list[tuple[str, list[NavItem]]] = [
    ("", [NavItem("Home", "home")]),
    ("Account", [NavItem("Profile", "accounts:profile")]),
    ("Administration", [NavItem("Platform admin", "admin:index", platform_admin_only=True)]),
]


def build_nav(request, perms):
    sections = []
    path = request.path
    for title, items in NAV_SECTIONS:
        visible = []
        for item in items:
            if item.platform_admin_only and not request.user.is_staff:
                continue
            if item.permissions is not None and not perms.intersection(item.permissions):
                continue
            try:
                url = reverse(item.url_name)
            except NoReverseMatch:
                continue
            active = path == url if url == "/" else path.startswith(url)
            visible.append({"label": item.label, "url": url, "active": active})
        if visible:
            sections.append({"title": title, "items": visible})
    return sections
