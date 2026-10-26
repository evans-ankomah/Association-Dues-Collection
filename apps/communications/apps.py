from django.apps import AppConfig


class CommunicationsConfig(AppConfig):
    name = "apps.communications"
    label = "communications"

    def ready(self):
        from . import receivers  # noqa: F401
