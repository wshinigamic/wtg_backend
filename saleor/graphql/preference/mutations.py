from collections import defaultdict

import graphene

from ...preference import models
from ...search.search import get_scores_update
from ..core.mutations import BaseMutation
from ..core.types import ProductError, NonNullList
from ..product.types import ProductColor



class ProductColorBulkPreferenceUpdate(BaseMutation):
    count_color_scores = graphene.Int(
        required=True,
        default_value=0,
        description="Returns how many ProductColorScore objects were updated.",
    )
    count_product_scores = graphene.Int(
        required=True,
        default_value=0,
        description="Returns how many ProductScore objects were updated.",
    )

    class Arguments:
        disliked_ids = NonNullList(
            graphene.ID, required=True, description="List of IDs of disliked product colors."
        )
        neutral_ids = NonNullList(
            graphene.ID, required=True, description="List of IDs of neutral product colors."
        )

    class Meta:
        #TODO: see if meta should include object_type, permissions, more accurate error_type_class and error_type_field.
        #TODO: error handling
        description = "Updates the dislike history of disliked product colors and scores of related product colors."
        error_type_class = ProductError

    @classmethod
    def perform_mutation(cls, _root, info, disliked_ids, neutral_ids):
        user = info.context.user
        product_preference = models.ProductPreference.objects.get(user=user)
        product_colors_dislike = cls.get_nodes_or_error(disliked_ids, "id", only_type=ProductColor)
        product_colors_neutral = cls.get_nodes_or_error(neutral_ids, "id", only_type=ProductColor)

        # First, bulk update dislike history
        disliked_product_colors = [models.DislikedProductColor(
            product_preference = product_preference, product_color = product_color
        ) for product_color in product_colors_dislike]
        models.DislikedProductColor.objects.bulk_create(disliked_product_colors)

        # Then, bulk update product_color_scores
        disliked_product_color_ids = [product_color.id for product_color in product_colors_dislike]
        neutral_product_color_ids = [product_color.id for product_color in product_colors_neutral]
        disliked_delta, disliked_ids, neutral_delta, neutral_ids = get_scores_update(
            disliked_product_color_ids, neutral_product_color_ids
        )

        product_preference = models.ProductPreference.objects.get(user=user)
        product_color_scores = models.ProductColorScore.objects.filter(
            product_score__product_preference = product_preference,
            product_color_id__in = disliked_ids + neutral_ids
        ).select_related("product_score").order_by("id")

        ids_to_delta = defaultdict(int)
        for id_, delta in zip(disliked_ids+neutral_ids, disliked_delta+neutral_delta):
            ids_to_delta[id_] += delta    

        product_score_map = defaultdict(list)
        product_score_objs = []

        for product_color_score in product_color_scores:
            product_color_score.score += ids_to_delta[product_color_score.pk]
            product_score = product_color_score.product_score
            product_score_map[product_score].append(product_color_score.score)
        for product_score, scores in product_score_map.items():
            product_score.score = min(scores)
            product_score_objs.append(product_score)

        models.ProductColorScore.objects.bulk_update(product_color_scores, ["score"], batch_size=1000)
        models.ProductScore.objects.bulk_update(product_score_objs, ["score"], batch_size=1000)

        return cls(count_color_scores=len(product_color_scores), count_product_scores=len(product_score_objs))