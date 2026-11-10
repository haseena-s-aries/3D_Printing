from django.apps import AppConfig


class IntelligenceConfig(AppConfig):
    name = "apps.intelligence"
    label = "intelligence"
    verbose_name = "Part intelligence (CN-007)"

    def ready(self):
        from . import runs  # noqa: F401  (registers the assessment-run job handler)
