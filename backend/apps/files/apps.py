from django.apps import AppConfig


class FilesConfig(AppConfig):
    name = "apps.files"
    label = "files"

    def ready(self):
        from . import jobs  # noqa: F401  (registers job handlers)
