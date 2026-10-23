import factory
from decimal import Decimal

from apps.accounts.tests.factories import UserFactory
from apps.llm.models import UsageRecord


class UsageRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UsageRecord

    user = factory.SubFactory(UserFactory)
    purpose = UsageRecord.Purpose.ASK
    provider = "gemini"
    model = "gemini-3.8-flash"
    prompt_tokens = 1000
    completion_tokens = 300
    latency_ms = 900
    cost_usd = factory.LazyFunction(lambda: Decimal("0.002"))
