from collections import defaultdict

import graphene
from django.core.exceptions import ValidationError
from graphene import relay
from graphql import GraphQLError

from ...accommodation import models
from ...core.permissions import ProductPermissions
from ...core.tracing import traced_atomic_transaction
from ...product.error_codes import ProductErrorCode
from ...thumbnail.utils import get_image_or_proxy_url, get_thumbnail_size
from ..account.dataloaders import AddressByIdLoader
from ..account.i18n import I18nMixin
from ..account.types import Address, AddressInput
from ..core.connection import CountableConnection, create_connection_slice, filter_connection_queryset
from ..core.fields import FilterConnectionField
from ..core.mutations import ModelMutation
from ..core.types import AccountError, Image, ModelObjectType, NonNullList, ThumbnailField, Upload
from ..core.utils import from_global_id_or_error
from ..core.validators.file import clean_image_file
from .dataloaders import ThumbnailByAccommodationIdSizeAndFormatLoader
from .filters import AccommodationFilterInput
from .sorters import AccommodationOrder, AccommodationOrderField


def search_string_in_kwargs(kwargs):
    return bool(kwargs.get("filter", {}).get("search_query", "").strip())


def sort_field_from_kwargs(kwargs):
    return kwargs.get("sort_by", {}).get("field") or None


class Accommodation(ModelObjectType):
    id = graphene.GlobalID(required=True)
    name = graphene.String(required=True)
    logo_image = ThumbnailField()
    address = graphene.Field(Address)
    website_url = graphene.String()
    isActive = graphene.Boolean()

    class Meta:
        model = models.Accommodation
        description = "Represents an accommodation."
        interfaces = [relay.Node]

    @staticmethod
    def resolve_logo_image(root, info, size=None, format=None):
        # node = root.node
        if not root.logo_image:
            return

        if not size:
            return Image(url=root.logo_image.url)

        format = format.lower() if format else None
        size = get_thumbnail_size(size)

        def _resolve_background_image(thumbnail):
            url = get_image_or_proxy_url(thumbnail, root.id, "Vendor", size, format)
            return Image(url=url)

        return (
            ThumbnailByAccommodationIdSizeAndFormatLoader(info.context)
            .load((root.id, size, format))
            .then(_resolve_background_image)
        )


class AccommodationCountableConnection(CountableConnection):
    class Meta:
        node = Accommodation


class AccommodationQueries(graphene.ObjectType):
    # TODO: consider if beneficial to use FilterConnectionField
    accommodations = FilterConnectionField(
        AccommodationCountableConnection,
        filter=AccommodationFilterInput(description="Filtering options for accommodations."),
        sort_by=AccommodationOrder(description="Sort accommodations."),
        description=(
            "List of accommodations."
        )
    )

    accommodation = graphene.Field(
        Accommodation,
        id=graphene.Argument(graphene.ID, description="ID of the accommodation.")
    )

    @staticmethod
    def resolve_accommodations(_root, info, **kwargs):
        print(kwargs)
        if sort_field_from_kwargs(kwargs) == AccommodationOrderField.SIMILARITY:
            if not search_string_in_kwargs(kwargs):
                raise GraphQLError(
                    "Sorting by SIMILARITY is available only when using a searchQuery filter."
                )
        qs = models.Accommodation.objects.all()
        qs = filter_connection_queryset(qs, kwargs)

        return create_connection_slice(qs, info, kwargs, AccommodationCountableConnection)

    @staticmethod
    def resolve_accommodation(_root, info, id):
        _type, id = from_global_id_or_error(id, Accommodation)
        return models.Accommodation.objects.filter(pk=id).first()

    @staticmethod
    def resolve_address(root, info):
        return AddressByIdLoader(info.context).load(root.address_id)


class AccommodationInput(graphene.InputObjectType):
    name = graphene.String(description="Accommodation name")
    logo_image = Upload(
        required=False, description="Represents a logo image file in a multipart request."
    )
    address = AddressInput(
        required=False, description="Address of the accommodation",
    )
    website_url = graphene.String(description="Website of the accommodation", required=False)
    isActive = graphene.Boolean(default_value=False, description="Active status of the accommodation.")


class AccommodationCreate(ModelMutation, I18nMixin):
    accommodation = graphene.Field(Accommodation)

    class Arguments:
        input = AccommodationInput(
            description="Fields required to create an accommodation.", required=True
        )

    class Meta:
        # Set proper permission.
        description = "Create an accommodation."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        model = models.Accommodation
        object_type = Accommodation
        error_type_class = AccountError # TODO: create proper error class

    @classmethod
    def clean_input(cls, info, instance, data):
        print("cleaned_input_accom", instance, data)
        cleaned_input = super().clean_input(info, instance, data)
        if data.get("logo_image"):
            clean_image_file(cleaned_input, "logo_image", ProductErrorCode)

        return cleaned_input

    @classmethod
    def prepare_address(cls, cleaned_data, *args):
        address_form = cls.validate_address_form(cleaned_data["address"])
        return address_form.save()

    @classmethod
    def construct_instance(cls, instance, cleaned_data):
        cleaned_data["address"] = cls.prepare_address(cleaned_data, instance)
        return super().construct_instance(instance, cleaned_data)


class AccommodationBulkCreate(ModelMutation, I18nMixin):
    count = graphene.Int(
        required=True,
        default_value=0,
        description="Returns how many objects were created.",
    )
    accommodations = NonNullList(
        Accommodation,
        required=True,
        default_value=[],
        description="List of created accommodations.",
    )

    class Arguments:
        accommodations = NonNullList(
            AccommodationInput,
            required=True,
            description="Input list of accommodations to create."
        )

    class Meta:
         # Set proper permission.
        description = "Create multiple accommodations."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        model = models.Accommodation
        object_type = Accommodation
        error_type_class = AccountError # TODO: create proper error class

    @classmethod
    def prepare_address(cls, cleaned_data, *args):
        address_form = cls.validate_address_form(cleaned_data["address"])
        return address_form.save()

    @classmethod
    def add_indexes_to_errors(cls, index, error, error_dict):
        """Append errors with index in params to mutation error dict."""
        for key, value in error.error_dict.items():
            for e in value:
                if e.params:
                    e.params["index"] = index
                else:
                    e.params = {"index": index}
            error_dict[key].extend(value)

    @classmethod
    def clean_input(cls, info, instance, data):
        print("cleaned_input_accoms", instance, data)
        cleaned_input = super().clean_input(info, instance, data, input_cls=AccommodationInput)
        if data.get("logo_image"):
            clean_image_file(cleaned_input, "logo_image", ProductErrorCode)
        return cleaned_input

    @classmethod
    def clean_accommodations(cls, info, accommodations):
        cleaned_inputs = []
        instance = models.Accommodation()
        for accommodation_data in accommodations:
            cleaned_inputs.append(cls.clean_input(info, instance, accommodation_data))
        return cleaned_inputs

    @classmethod
    def create_accommodations(cls, info, cleaned_inputs, errors):
        instances = []
        for index, cleaned_input in enumerate(cleaned_inputs):
            if not cleaned_input:
                continue
            try:
                instance = models.Accommodation()
                cleaned_input["address"] = cls.prepare_address(cleaned_input, instance)
                print(instance)
                instance = cls.construct_instance(instance, cleaned_input)
                print(instance)
                cls.clean_instance(info, instance)
                instances.append(instance)
            except ValidationError as exc:
                cls.add_indexes_to_errors(index, exc, errors)
        return instances

    @classmethod
    def save_accommodations(cls, info, instances, cleaned_inputs):
        assert len(instances) == len(
            cleaned_inputs
        ), "There should be the same number of instances and cleaned inputs."
        for instance, cleaned_input in zip(instances, cleaned_inputs):
            cls.save(info, instance, cleaned_input)

    @classmethod
    @traced_atomic_transaction()
    def perform_mutation(cls, _root, info, **data):
        errors = defaultdict(list)
        cleaned_inputs = cls.clean_accommodations(info, data["accommodations"])
        instances = cls.create_accommodations(info, cleaned_inputs, errors)
        if errors:
            raise ValidationError(errors)
        cls.save_accommodations(info, instances, cleaned_inputs)

        # TODO: check if need to do transaction.on_commit

        return AccommodationBulkCreate(
            count=len(instances), accommodations=instances
        )

class AccommodationMutations(graphene.ObjectType):
    accommodation_create = AccommodationCreate.Field()
    accommodation_bulk_create = AccommodationBulkCreate.Field()