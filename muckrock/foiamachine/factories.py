"""
Factories for generating FOIA Machine model instances
"""

from django.utils.text import slugify

import factory

from muckrock import factories as muckrock_factories
from muckrock.jurisdiction import factories as jurisdiction_factories
from muckrock.foiamachine.models import FoiaMachineRequest

class FoiaMachineRequestFactory(factory.django.DjangoModelFactory):
    """A factory for creating FoiaMachineRequest objects."""
    class Meta:
        model = FoiaMachineRequest

    title = factory.Sequence(lambda n: "FOIA Machine Request %d" % n)
    slug = factory.LazyAttribute(lambda obj: slugify(obj.title))
    user = factory.SubFactory(muckrock_factories.UserFactory)
    jurisdiction = factory.SubFactory(jurisdiction_factories.StateJurisdictionFactory)
