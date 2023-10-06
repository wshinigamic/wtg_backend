from collections import defaultdict

from ...preference.models import ProductColor
from ...product.models import ProductVariant

from ..core.dataloaders import DataLoader
from ..product.dataloaders import ProductVariantByIdLoader


class ProductVariantsByProductColorIdLoader(DataLoader):
    context_key = "productvariants_by_productcolor"

    def batch_load(self, keys):
        product_colors = ProductColor.objects.using(self.database_connection_name).filter(id__in=keys).values_list("id", "product_id", "color_id")
        variant_map = defaultdict(list)
        variant_loader = ProductVariantByIdLoader(self.context)

        # TODO: see if this nested loop can be made more efficient
        for product_color_id, product_id, color_id in product_colors:
            variants = ProductVariant.objects.using(self.database_connection_name).filter(
                product_id=product_id, attributes__values__id=color_id
            )
            for variant in variants.iterator():
                variant_map[product_color_id].append(variant)
                variant_loader.prime(variant.id, variant)

        return [variant_map.get(product_color_id, []) for product_color_id in keys]


class ProductVariantsByProductColorIdAndChannel(DataLoader):
    context_key = "productvariants_by_productcolor_and_channel"

    def batch_load(self, keys):
        product_color_ids, channel_slugs = zip(*keys)
        product_colors = ProductColor.objects.using(self.database_connection_name).filter(id__in=product_color_ids).values_list("id", "product_id", "color_id")
        variant_map = defaultdict(list)

        for product_color_id, product_id, color_id in product_colors:
            variants_filter = self.get_variants_filter(product_id, color_id, channel_slugs)
            variants = (
                ProductVariant.objects.using(self.database_connection_name)
                .filter(**variants_filter)
                .annotate(channel_slug=F("channel_listings__channel__slug"))
            )
            for variant in variants.iterator():
                variant_map[(product_color_id, variant.channel_slug)].append(variant)

        return [variant_map.get(key, []) for key in keys]

    def get_variants_filter(self, product_id, color_id, channel_slugs):
        return {
            "product_id": product_id,
            "attributes__values__id": color_id,
            "channel_listings__channel__slug__in": [
                str(slug) for slug in channel_slugs
            ],
        }


class AvailableProductVariantsByProductColorIdAndChannel(
    ProductVariantsByProductColorIdAndChannel
):
    context_key = "available_productvariants_by_productcolor_and_channel"

    def get_variants_filter(self, product_id, color_id, channel_slugs):
        return {
            "product_id": product_id,
            "attributes__values__id": color_id,
            "channel_listings__channel__slug__in": [
                str(slug) for slug in channel_slugs
            ],
            "channel_listings__price_amount__isnull": False,
        }
