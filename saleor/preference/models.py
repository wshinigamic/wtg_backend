
import uuid

from django.db import models

from ..account.models import User
from ..attribute.models import AttributeValue
from ..channel.models import Channel
from ..core.models import ModelWithMetadata
from ..product.models import Product, ProductVariant


class ProductColor(ModelWithMetadata):
    # TODO: Put it here instead of under saleor > product due to circular import
    # but there is probably a better place
    # graphql productcolor is in product 
    product = models.ForeignKey(
        Product, related_name="product_color", on_delete=models.CASCADE
    )
    color = models.ForeignKey(
        AttributeValue, related_name="product_color", on_delete=models.CASCADE
    )
    neural_representation = models.BinaryField(null=True, blank=True)
    cluster = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("product", "color")


class ProductColorChannelListing(models.Model):
    product_color = models.ForeignKey(
        ProductColor,
        null=False,
        blank=False,
        related_name="channel_listings",
        on_delete=models.CASCADE
    )
    channel = models.ForeignKey(
        Channel,
        null=False,
        blank=False,
        related_name="product_color_listings",
        on_delete=models.CASCADE
    )

    class Meta:
        unique_together = [["product_color", "channel"]]
        ordering = ("pk",)



class ProductPreference(models.Model):
    # TODO: check if concept is correct: By having UUID and optional user,
    # users don't need to have an account before having scores for products,
    # dislikelist, and wishlist.
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.OneToOneField(
        User, related_name="product_preference", on_delete=models.CASCADE, blank=True, null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def set_user(self, user):
        self.user = user
        self.save()

    def dislike_product_color(self, product_color: ProductColor):
        # Should update DislikedProductColor, ProductColorScore, and ProductScore
        # or do inside mutation?
        pass

    def remove_disliked_product_color(self, product_color: ProductColor):
        # Should update DislikedProductColor, ProductColorScore, and ProductScore
        # or do inside mutation?
        pass

    def add_wishlist_variant(self, variant: ProductVariant):
        pass

    def remove_wishlist_variant(self, variant: ProductVariant):
        pass


class ProductScore(models.Model):
    product_preference = models.ForeignKey(
        ProductPreference, related_name="product_score", on_delete=models.CASCADE
    )
    product = models.ForeignKey(
        Product, related_name="product_score", on_delete=models.CASCADE
    )
    score = models.FloatField(default=0.0)

    class Meta:
        unique_together = ("product_preference", "product")


class ProductColorScore(models.Model):
    product_score = models.ForeignKey(
        ProductScore, related_name="product_color_score", on_delete=models.CASCADE
    )
    product_color = models.ForeignKey(
        ProductColor, related_name="product_color_score", on_delete=models.CASCADE
    )
    score = models.FloatField(default=0.0)

    class Meta:
        unique_together = ("product_score", "product_color")


class DislikedProductColor(models.Model):
    #TODO: check if not normalizing this is ok
    product_preference = models.ForeignKey(
        ProductPreference, related_name="disliked_product_color", on_delete=models.CASCADE
    )
    product_color = models.ForeignKey(
        ProductColor, related_name="disliked_product_color", on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("product_preference", "product_color", "created_at")


class WishlistVariant(models.Model):
    # Track product variant for wishlist and display by product variant.
    product_preference = models.ForeignKey(
        ProductPreference, related_name="wishlist_variant", on_delete=models.CASCADE
    )
    variant = models.ForeignKey(
        ProductVariant, related_name="wishlist_variant", on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("product_preference", "variant")