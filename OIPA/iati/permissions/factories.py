from django.contrib.auth.models import User
from factory import RelatedFactory, SubFactory
from factory.django import DjangoModelFactory

from iati.permissions.models import (
    OrganisationAdminGroup, OrganisationGroup, OrganisationUser
)
from iati_synchroniser.factory import synchroniser_factory


class OrganisationUserFactory(DjangoModelFactory):
    user = SubFactory('iati.permissions.factories.UserFactory',
                      organisationuser=None)

    class Meta:
        model = OrganisationUser  # Equivalent to ``model = myapp.models.User``


class UserFactory(DjangoModelFactory):
    username = 'john'
    organisationuser = RelatedFactory(OrganisationUserFactory, 'user')

    class Meta:
        model = User  # Equivalent to ``model = myapp.models.User``
        django_get_or_create = ('username',)


class OrganisationAdminGroupFactory(DjangoModelFactory):
    name = "DFID Organisation Admin Group"
    publisher = SubFactory(synchroniser_factory.PublisherFactory)
    owner = SubFactory(OrganisationUserFactory)

    class Meta:
        model = OrganisationAdminGroup


class OrganisationGroupFactory(DjangoModelFactory):
    name = "DFID Organisation Organisation Group"
    publisher = SubFactory(synchroniser_factory.PublisherFactory)

    class Meta:
        model = OrganisationGroup
