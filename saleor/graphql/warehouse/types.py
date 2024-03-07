import graphene
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from ...permission.enums import OrderPermissions, ProductPermissions
from ...warehouse import models
from ...warehouse.reservations import is_reservation_enabled
from ..account.dataloaders import AddressByIdLoader
from ..channel import ChannelContext
from ..core import ResolveInfo
from ..core.connection import CountableConnection, create_connection_slice
from ..core.descriptions import (
    ADDED_IN_31,
    ADDED_IN_310,
    DEPRECATED_IN_3X_FIELD,
    DEPRECATED_IN_3X_INPUT,
)
from ..core.doc_category import DOC_CATEGORY_PRODUCTS
from ..core.fields import ConnectionField, PermissionsField
from ..core.types import (
    BaseInputObjectType,
    BaseObjectType,
    ModelObjectType,
    NonNullList,
)
from ..meta.types import ObjectWithMetadata
from ..product.dataloaders import ProductVariantByIdLoader
from ..site.dataloaders import load_site_callback
from .dataloaders import WarehouseByIdLoader
from .enums import WarehouseClickAndCollectOptionEnum


class WarehouseInput(BaseInputObjectType):
    slug = graphene.String(description="Warehouse slug.")
    email = graphene.String(description="The email address of the warehouse.")
    external_reference = graphene.String(
        description="External ID of the warehouse." + ADDED_IN_310, required=False
    )

    class Meta:
        doc_category = DOC_CATEGORY_PRODUCTS


class WarehouseCreateInput(WarehouseInput):
    name = graphene.String(description="Warehouse name.", required=True)
    address = graphene.Field(
        "saleor.graphql.account.types.AddressInput",
        description="Address of the warehouse.",
        required=True,
    )
    shipping_zones = NonNullList(
        graphene.ID,
        description="Shipping zones supported by the warehouse."
        + DEPRECATED_IN_3X_INPUT
        + " Providing the zone ids will raise a ValidationError.",
    )

    class Meta:
        doc_category = DOC_CATEGORY_PRODUCTS


class WarehouseUpdateInput(WarehouseInput):
    name = graphene.String(description="Warehouse name.", required=False)
    address = graphene.Field(
        "saleor.graphql.account.types.AddressInput",
        description="Address of the warehouse.",
        required=False,
    )
    click_and_collect_option = WarehouseClickAndCollectOptionEnum(
        description=(
            "Click and collect options: local, all or disabled." + ADDED_IN_31
        ),
        required=False,
    )
    is_private = graphene.Boolean(
        description="Visibility of warehouse stocks." + ADDED_IN_31,
        required=False,
    )

    class Meta:
        doc_category = DOC_CATEGORY_PRODUCTS


class Warehouse(ModelObjectType[models.Warehouse]):
    id = graphene.GlobalID(required=True, description="The ID of the warehouse.")
    name = graphene.String(required=True, description="Warehouse name.")
    slug = graphene.String(required=True, description="Warehouse slug.")
    email = graphene.String(required=True, description="Warehouse email.")
    is_private = graphene.Boolean(
        required=True, description="Determine if the warehouse is private."
    )
    address = graphene.Field(
        "saleor.graphql.account.types.Address",
        required=True,
        description="Address of the warehouse.",
    )
    company_name = graphene.String(
        required=True,
        description="Warehouse company name.",
        deprecation_reason=(
            f"{DEPRECATED_IN_3X_FIELD} Use `Address.companyName` instead."
        ),
    )
    click_and_collect_option = WarehouseClickAndCollectOptionEnum(
        description=(
            "Click and collect options: local, all or disabled." + ADDED_IN_31
        ),
        required=True,
    )
    shipping_zones = ConnectionField(
        "saleor.graphql.shipping.types.ShippingZoneCountableConnection",
        required=True,
        description="Shipping zones supported by the warehouse.",
    )
    external_reference = graphene.String(
        description=f"External ID of this warehouse. {ADDED_IN_310}", required=False
    )

    class Meta:
        description = "Represents warehouse."
        model = models.Warehouse
        interfaces = [graphene.relay.Node, ObjectWithMetadata]

    @staticmethod
    def resolve_shipping_zones(root, info: ResolveInfo, *_args, **kwargs):
        from ..shipping.types import ShippingZoneCountableConnection

        instances = root.shipping_zones.all()
        slice = create_connection_slice(
            instances, info, kwargs, ShippingZoneCountableConnection
        )

        edges_with_context = []
        for edge in slice.edges:
            node = edge.node
            edge.node = ChannelContext(node=node, channel_slug=None)
            edges_with_context.append(edge)
        slice.edges = edges_with_context

        return slice

    @staticmethod
    def resolve_address(root, info: ResolveInfo):
        if hasattr(root, "is_object_deleted") and root.is_object_deleted:
            return root.address

        return AddressByIdLoader(info.context).load(root.address_id)

    @staticmethod
    def resolve_company_name(root, info: ResolveInfo):
        def _resolve_company_name(address):
            return address.company_name

        return (
            AddressByIdLoader(info.context)
            .load(root.address_id)
            .then(_resolve_company_name)
        )


class WarehouseCountableConnection(CountableConnection):
    class Meta:
        doc_category = DOC_CATEGORY_PRODUCTS
        node = Warehouse


class Stock(ModelObjectType[models.Stock]):
    id = graphene.GlobalID(required=True, description="The ID of stock.")
    warehouse = graphene.Field(
        Warehouse, required=True, description="The warehouse associated with the stock."
    )
    product_variant = graphene.Field(
        "saleor.graphql.product.types.ProductVariant",
        required=True,
        description="Information about the product variant.",
    )
    quantity = PermissionsField(
        graphene.Int,
        required=True,
        description=(
            "Quantity of a product in the warehouse's possession, including the "
            "allocated stock that is waiting for shipment."
        ),
        permissions=[
            ProductPermissions.MANAGE_PRODUCTS,
            OrderPermissions.MANAGE_ORDERS,
        ],
    )
    quantity_allocated = PermissionsField(
        graphene.Int,
        required=True,
        description="Quantity allocated for orders.",
        datetime_start=graphene.Argument(
            graphene.DateTime,
            required=False,
            description="Start of datetime range to check stocks information."
        ),
        datetime_end=graphene.Argument(
            graphene.DateTime,
            required=False,
            description="End of datetime range to check stocks information."
        ),
        permissions=[
            ProductPermissions.MANAGE_PRODUCTS,
            OrderPermissions.MANAGE_ORDERS,
        ],
    )
    quantity_reserved = PermissionsField(
        graphene.Int,
        required=True,
        description="Quantity reserved for checkouts.",
        datetime_start=graphene.Argument(
            graphene.DateTime,
            required=False,
            description="Start of datetime range to check stocks information."
        ),
        datetime_end=graphene.Argument(
            graphene.DateTime,
            required=False,
            description="End of datetime range to check stocks information."
        ),
        permissions=[
            ProductPermissions.MANAGE_PRODUCTS,
            OrderPermissions.MANAGE_ORDERS,
        ],
    )
    quantity_available = PermissionsField(
        graphene.Int,
        required=True,
        description="Quantity available for checkouts.",
        datetime_start=graphene.Argument(
            graphene.DateTime,
            required=False,
            description="Start of datetime range to check stocks information."
        ),
        datetime_end=graphene.Argument(
            graphene.DateTime,
            required=False,
            description="End of datetime range to check stocks information."
        ),
        permissions=[
            ProductPermissions.MANAGE_PRODUCTS,
            OrderPermissions.MANAGE_ORDERS,
        ],
    )

    class Meta:
        description = "Represents stock."
        model = models.Stock
        interfaces = [graphene.relay.Node]

    @staticmethod
    def resolve_quantity(root, _info: ResolveInfo):
        return root.quantity

    @staticmethod
    def resolve_quantity_allocated(root, _info: ResolveInfo, datetime_start=None, datetime_end=None):
        if datetime_start is not None and datetime_end is not None:
            return root.allocations.aggregate(
                quantity_allocated=Coalesce(
                    Sum(
                        "quantity_allocated",
                        filter=(
                            (Q(order_line__order__rental_start__gte=datetime_start) &
                            Q(order_line__order__rental_start__lte=datetime_end)) |
                            (Q(order_line__order__rental_end__gte=datetime_start) &
                            Q(order_line__order__rental_end__lte=datetime_end))
                        )
                    ),
                    0,
                )
            )["quantity_allocated"]
        return root.allocated_quantity

    @staticmethod
    @load_site_callback
    def resolve_quantity_reserved(root, _info: ResolveInfo, site, datetime_start=None, datetime_end=None):
        if not is_reservation_enabled(site.settings):
            return 0

        if datetime_start is not None and datetime_end is not None:
            return root.reservations.aggregate(
                quantity_reserved=Coalesce(
                    Sum(
                        "quantity_reserved",
                        filter=(
                            Q(reserved_until__gt=timezone.now()),
                            (Q(checkout_line__checkout__rental_start__gte=datetime_start) &
                            Q(checkout_line__checkout__rental_start__lte=datetime_end)) |
                            (Q(checkout_line__checkout__rental_end__gte=datetime_start) &
                            Q(checkout_line__checkout__rental_end__lte=datetime_end))
                        )
                    ),
                    0,
                )
            )["quantity_reserved"]
        return root.reserved_quantity
    
    @staticmethod
    def resolve_quantity_available(root, _info: ResolveInfo, datetime_start=None, datetime_end=None):
        if datetime_start is not None and datetime_end is not None:
            return root.quantity - root.allocations.aggregate(
                quantity_allocated=Coalesce(
                    Sum(
                        "quantity_allocated",
                        filter=(
                            (Q(order_line__order__rental_start__gte=datetime_start) &
                            Q(order_line__order__rental_start__lte=datetime_end)) |
                            (Q(order_line__order__rental_end__gte=datetime_start) &
                            Q(order_line__order__rental_end__lte=datetime_end))
                        )
                    ),
                    0,
                )
            )["quantity_allocated"]
        return root.available_quantity

    @staticmethod
    def resolve_warehouse(root, info: ResolveInfo):
        if root.warehouse_id:
            return WarehouseByIdLoader(info.context).load(root.warehouse_id)
        return None

    @staticmethod
    def resolve_product_variant(root, info: ResolveInfo):
        return (
            ProductVariantByIdLoader(info.context)
            .load(root.product_variant_id)
            .then(lambda variant: ChannelContext(node=variant, channel_slug=None))
        )


class StockCountableConnection(CountableConnection):
    class Meta:
        doc_category = DOC_CATEGORY_PRODUCTS
        node = Stock


class Allocation(BaseObjectType):
    id = graphene.GlobalID(required=True, description="The ID of allocation.")
    quantity = PermissionsField(
        graphene.Int,
        required=True,
        description="Quantity allocated for orders.",
        permissions=[
            ProductPermissions.MANAGE_PRODUCTS,
            OrderPermissions.MANAGE_ORDERS,
        ],
    )
    warehouse = PermissionsField(
        Warehouse,
        required=True,
        description="The warehouse were items were allocated.",
        permissions=[
            ProductPermissions.MANAGE_PRODUCTS,
            OrderPermissions.MANAGE_ORDERS,
        ],
    )

    class Meta:
        description = "Represents allocation."
        doc_category = DOC_CATEGORY_PRODUCTS
        model = models.Allocation
        interfaces = [graphene.relay.Node]

    @staticmethod
    def get_node(_info, id):
        try:
            return models.Allocation.objects.get(pk=id)
        except models.Allocation.DoesNotExist:
            return None

    @staticmethod
    def resolve_warehouse(root, _info: ResolveInfo):
        return root.stock.warehouse

    @staticmethod
    def resolve_quantity(root, _info: ResolveInfo):
        return root.quantity_allocated
