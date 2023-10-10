from collections import defaultdict

import graphene
from django.db.models import F, OuterRef, Subquery
from graphene import relay

from ...permission.utils import has_one_of_permissions
from ...preference import models
from ...product.models import ALL_PRODUCTS_PERMISSIONS

from ..channel import ChannelContext
from ..channel.types import ChannelContextType
from ..core.connection import CountableConnection
from ..core.dataloaders import DataLoader
from ..core.types import ModelObjectType
from ..meta.types import ObjectWithMetadata
from ..product.types import Product
from ..product.dataloaders.products import ProductColorByIdLoader
from ..utils import get_user_or_app_from_context




class ProductColorsWPreferenceByProductIdLoader(DataLoader):
    context_key = "productcolors_w_preference_by_product"

    def batch_load(self, keys):
        user = self.context.user

        product_colors = models.ProductColor.objects.filter(
            product_id__in=keys
        )
        qs2 = (
            models.ProductColorScore.objects.filter(
                product_score__product_preference__user=user,
                product_score__product_id__in=keys,
                product_color=OuterRef("pk")
            )
        )
        product_colors = product_colors.annotate(score=Subquery(qs2.values("score"))).order_by(F("score").desc(nulls_last=True))
        product_color_map = defaultdict(list)
        product_color_loader = ProductColorByIdLoader(self.context)
        for product_color in product_colors.iterator():
            product_color_map[product_color.product_id].append(product_color)
            product_color_loader.prime(product_color.id, product_color)
        return [product_color_map.get(product_id, []) for product_id in keys]


class ProductColorsWPreferenceByProductIdAndChannel(DataLoader):
    context_key = "productcolors_w_preference_by_product_and_channel"

    def batch_load(self, keys):
        user = self.context.user

        product_ids, channel_slugs = zip(*keys)
        product_colors_filter = self.get_product_colors_filter(product_ids, channel_slugs)
        product_colors = (
            models.ProductColor.objects.using(self.database_connection_name)
            .filter(**product_colors_filter)
            .annotate(channel_slug=F("channel_listings__channel__slug"))
        )
        qs2 = (
            models.ProductColorScore.objects.filter(
                product_score__product_preference__user=user,
                product_score__product_id__in=keys,
                product_color=OuterRef("pk")
            )
        )
        product_colors = product_colors.annotate(score=Subquery(qs2.values("score"))).order_by(F("score").desc(nulls_last=True))
        product_color_map = defaultdict(list)
        for product_color in product_colors.iterator():
            product_color_map[(product_color.product_id, product_color.channel_slug)].append(product_color)

        return [product_color_map.get(key, []) for key in keys]

    def get_product_colors_filter(self, products_ids, channel_slugs):
        return {
            "product_id__in": products_ids,
            "channel_listings__channel__slug__in": [
                str(slug) for slug in channel_slugs
            ],
        }


class AvailableProductColorsWPreferenceByProductIdAndChannel(
    ProductColorsWPreferenceByProductIdAndChannel
):
    # TODO: No difference with parent currently.
    context_key = "available_productcolors_w_preference_by_product_and_channel"

    def get_product_colors_filter(self, products_ids, channel_slugs):
        return {
            "product_id__in": products_ids,
            "channel_listings__channel__slug__in": [
                str(slug) for slug in channel_slugs
            ],
            # "channel_listings__price_amount__isnull": False,
        }


class ProductWPreference(Product):
    class Meta:
        default_resolver = ChannelContextType.resolver_with_context
        description = "Represents a user's preference for an individual item."
        interfaces = [relay.Node, ObjectWithMetadata]
        model = models.Product

    @staticmethod
    def resolve_product_colors(root: ChannelContext[models.Product], info):
        requestor = get_user_or_app_from_context(info.context)
        has_required_permissions = has_one_of_permissions(
            requestor, ALL_PRODUCTS_PERMISSIONS
        )
        if has_required_permissions and not root.channel_slug:
            product_colors = ProductColorsWPreferenceByProductIdLoader(info.context).load(root.node.id)
        elif has_required_permissions and root.channel_slug:
            product_colors = ProductColorsWPreferenceByProductIdAndChannel(info.context).load(
                (root.node.id, root.channel_slug)
            )
        else:
            product_colors = AvailableProductColorsWPreferenceByProductIdAndChannel(info.context).load(
                (root.node.id, root.channel_slug)
            )

        def map_channel_context(product_colors):
            return [
                ChannelContext(node=product_color, channel_slug=root.channel_slug)
                for product_color in product_colors
            ]

        return product_colors.then(map_channel_context)


class ProductWPreferenceCountableConnection(CountableConnection):
    class Meta:
        node = ProductWPreference


class ProductPreference(ModelObjectType):
    #TODO: check if need to change filter fields
    class Meta:
        only_fields = ["id", "created_at", "product_score", "disliked_product_color"]
        description = "Preference of a user."
        interfaces = [relay.Node]
        model = models.ProductPreference
        filter_fields = ["id"]


class ProductScore(ModelObjectType):
    #TODO: check if need to change filter fields
    class Meta:
        only_fields = ["id", "product_preference", "product", "score"]
        description = "Score of a product."
        interfaces = [relay.Node]
        model = models.ProductScore
        filter_fields = ["id"]


class ProductColorScore(ModelObjectType):
    #TODO: check if need to change filter fields
    class Meta:
        only_fields = ["id", "product_score", "product_color", "score"]
        description = "Score of a product color."
        interfaces = [relay.Node]
        model = models.ProductColorScore
        filter_fields = ["id"]


class DislikedProductColor(ModelObjectType):
    class Meta:
        only_fields = ["id", "product_preference", "product_color", "created_at"]
        description = "Record of a disliked product color."
        interfaces = [relay.Node]
        model = models.DislikedProductColor
        filter_fields = ["id"]


class DislikedProductColorCountableConnection(CountableConnection):
    class Meta:
        node = DislikedProductColor