from collections import defaultdict, namedtuple
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional

import graphene
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.utils import IntegrityError
from graphql import GraphQLError

from ...core.tracing import traced_atomic_transaction
from ...order import OrderStatus
from ...order import models as order_models
from ...warehouse.models import Stock, StockWTimePeriod
from ..core.enums import ProductErrorCode
from .sorters import ProductOrderField

if TYPE_CHECKING:
    from ...product.models import ProductVariant
    from ...warehouse.models import Warehouse

import logging

logger = logging.getLogger(__name__)


def get_used_attribute_values_for_variant(variant):
    """Create a dict of attributes values for variant.

    Sample result is:
    {
        "attribute_1_global_id": ["ValueAttr1_1"],
        "attribute_2_global_id": ["ValueAttr2_1"]
    }
    """
    attribute_values = defaultdict(list)
    for assigned_variant_attribute in variant.attributes.all():
        attribute = assigned_variant_attribute.attribute
        attribute_id = graphene.Node.to_global_id("Attribute", attribute.id)
        for attr_value in assigned_variant_attribute.values.all():
            attribute_values[attribute_id].append(attr_value.slug)
    return attribute_values


def get_used_variants_attribute_values(product):
    """Create list of attributes values for all existing `ProductVariants` for product.

    Sample result is:
    [
        {
            "attribute_1_global_id": ["ValueAttr1_1"],
            "attribute_2_global_id": ["ValueAttr2_1"]
        },
        ...
        {
            "attribute_1_global_id": ["ValueAttr1_2"],
            "attribute_2_global_id": ["ValueAttr2_2"]
        }
    ]
    """
    variants = (
        product.variants.prefetch_related("attributes__values")
        .prefetch_related("attributes__assignment")
        .all()
    )
    used_attribute_values = []
    for variant in variants:
        attribute_values = get_used_attribute_values_for_variant(variant)
        if attribute_values:
            used_attribute_values.append(attribute_values)
    return used_attribute_values


@traced_atomic_transaction()
def create_stocks(
    variant: "ProductVariant",
    stocks_data: List[Dict[str, str]],
    warehouses: Iterable["Warehouse"],
):
    # First, create "Stock" which is essentially just (warehouse, product_variant)
    # TODO: check if duplicated value is returned, if so, the query afterwards is not required
    Stock.objects.bulk_create(
        [Stock(
            warehouse=warehouse,
            product_variant=variant,
        ) for warehouse in set(warehouses)],
        ignore_conflicts=True
    )
    stocks = Stock.objects.filter(product_variant=variant, warehouse__in=set(warehouses))

    # Then, create "StockWTimePeriod"s.
    stocks_w_time_period = []
    for stock_data, warehouse in zip(stocks_data, warehouses):
        stock = stocks.get(warehouse=warehouse)
        stocks_w_time_period.append(StockWTimePeriod(
            stock=stock,
            availability_start=stock_data["availability_start"],
            availability_end=stock_data["availability_end"],
            quantity=stock_data["quantity"]
        ))

    try:
        StockWTimePeriod.objects.bulk_create(stocks_w_time_period)
    except IntegrityError:
        msg = "Duplicated StockWTimePeriod already exists."
        raise ValidationError(msg)
    return stocks


DraftOrderLinesData = namedtuple(
    "DraftOrderLinesData", ["order_to_lines_mapping", "line_pks", "order_pks"]
)


def get_draft_order_lines_data_for_variants(
    variant_ids: Iterable[int],
):
    lines = order_models.OrderLine.objects.filter(
        variant__id__in=variant_ids, order__status=OrderStatus.DRAFT
    ).select_related("order")
    order_to_lines_mapping: Dict[
        order_models.Order, List[order_models.OrderLine]
    ] = defaultdict(list)
    line_pks = set()
    order_pks = set()
    for line in lines:
        order_to_lines_mapping[line.order].append(line)
        line_pks.add(line.pk)
        order_pks.add(line.order_id)

    return DraftOrderLinesData(order_to_lines_mapping, line_pks, order_pks)


def clean_variant_sku(sku: Optional[str]) -> Optional[str]:
    if sku:
        return sku.strip() or None
    return None


def update_ordered_media(ordered_media):
    errors = defaultdict(list)
    with transaction.atomic():
        for order, media in enumerate(ordered_media):
            media.sort_order = order
            try:
                media.save(update_fields=["sort_order"])
            except DatabaseError as e:
                msg = (
                    f"Cannot update media for instance: {media}. "
                    "Updating not existing object. "
                    f"Details: {e}."
                )
                logger.warning(msg)
                errors["media"].append(
                    ValidationError(msg, code=ProductErrorCode.NOT_FOUND.value)
                )

    if errors:
        raise ValidationError(errors)


def search_string_in_kwargs(kwargs: dict) -> bool:
    filter_search = kwargs.get("filter", {}).get("search", "") or ""
    search = kwargs.get("search", "") or ""
    return bool(filter_search.strip()) or bool(search.strip())


def sort_field_from_kwargs(kwargs: dict) -> Optional[List[str]]:
    return kwargs.get("sort_by", {}).get("field") or None


def check_for_sorting_by_rank(info, kwargs: dict):
    if sort_field_from_kwargs(kwargs) == ProductOrderField.RANK:
        # sort by RANK can be used only with search filter
        if not search_string_in_kwargs(kwargs):
            raise GraphQLError(
                (
                    "Sorting by RANK is available only when using a search filter "
                    "or search argument."
                )
            )
    if search_string_in_kwargs(kwargs) and not sort_field_from_kwargs(kwargs):
        # default to sorting by RANK if search is used
        # and no explicit sorting is requested
        product_type = info.schema.get_type("ProductOrder")
        kwargs["sort_by"] = product_type.create_container(
            {"direction": "-", "field": ["search_rank", "id"]}
        )
