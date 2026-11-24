from django.apps import AppConfig


class AssistantConfig(AppConfig):
    """The in-app assistant (chatbot): answers questions about the platform and the person's own data, rule-based, with
    no external or paid AI service. Data comes from the same queries and visibility rules as the screens."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.assistant"
    label = "assistant"
