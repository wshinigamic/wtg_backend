import graphene
import numpy as np
import pandas as pd
from django.db.models import Exists, F, OuterRef, Subquery

from ...channel.models import Channel
from ...permission.utils import has_one_of_permissions
from ...preference import models
from ...product import models as product_models
from ...product.models import ALL_PRODUCTS_PERMISSIONS
from ..channel import ChannelContext, ChannelQsContext
from ..channel.utils import get_default_channel_slug_or_graphql_error
from ..core.connection import create_connection_slice, filter_connection_queryset
from ..core.context import get_database_connection_name
from ..core.fields import FilterConnectionField
from ..core.filters import GlobalIDMultipleChoiceFilter
from ..core.tracing import traced_resolver
from ..core.types import ChannelFilterInputObjectType
from ..core.utils import from_global_id_or_error
from ..core.validators import validate_one_of_args_is_in_query
from ..product.filters import ProductFilter
from ..product.resolvers import resolve_product
from ..utils import get_user_or_app_from_context
from ..utils.filters import filter_by_id
from .mutations import ProductColorBulkPreferenceUpdate
from .types import (
    DislikedProductColor,
    DislikedProductColorCountableConnection,
    ProductWPreference,
    ProductWPreferenceCountableConnection
)

class ProductWPreferenceFilter(ProductFilter):
    ids = GlobalIDMultipleChoiceFilter(method=filter_by_id("ProductWPreference"))

class ProductWPreferenceFilterInput(ChannelFilterInputObjectType):
    class Meta:
        filterset_class = ProductWPreferenceFilter

class PreferenceQueries(graphene.ObjectType):
    disliked_product_color = graphene.Field(
        DislikedProductColor,
        id=graphene.Argument(
            graphene.ID,
            description="ID of the disliked product color record."
        )
    )

    disliked_product_colors = FilterConnectionField(
        DislikedProductColorCountableConnection,
        description="List of disliked product colors."
    )

    #TODO: Think of an algo to sort and paginate by scores
    products_by_score = FilterConnectionField(
        ProductWPreferenceCountableConnection,
        filter=ProductWPreferenceFilterInput(description="Filtering options for products."),
        channel=graphene.String(
            description="Slug of a channel for which the data should be returned."
        ),
        description=(
            "List of products sorted by score."
        )
    )

    product_w_preference = graphene.Field(
        ProductWPreference,
        id=graphene.Argument(
            graphene.ID,
            description="ID of the product_w_preference."
        ),
        slug=graphene.Argument(graphene.String, description="Slug of the product."),
        channel=graphene.String(
            description="Slug of a channel for which the data should be returned."
        ),
        description=(
            "Look up a product_w_preference by ID. Requires one of the following permissions to "
            "include the unpublished items: "
            f"{', '.join([p.name for p in ALL_PRODUCTS_PERMISSIONS])}."
        )
    )

    @staticmethod
    @traced_resolver
    def resolve_disliked_product_color(_root, info: graphene.ResolveInfo, id):
        _type, id = from_global_id_or_error(id, models.DislikedProductColor)
        database_connection_name = get_database_connection_name(info.context)
        return (
            models.DislikedProductColor.objects.using(database_connection_name)
            .get(id=id)
        )

    @staticmethod
    @traced_resolver
    def resolve_disliked_product_colors(_root, info: graphene.ResolveInfo):
        #TODO: set appropriate permission
        user = info.context.user
        database_connection_name = get_database_connection_name(info.context)
        return (
            models.DislikedProductColor.objects.using(database_connection_name)
            .filter(product_preference__user=user)
        )

    @staticmethod
    @traced_resolver
    def resolve_products_by_score(_root, info: graphene.ResolveInfo, *, channel=None, **kwargs):
        #TODO: set appropriate permission
        #TODO: check how search filter should work with this
        #TODO: make this less hacky
        print("in resolve products by score", kwargs)
        requestor = get_user_or_app_from_context(info.context)
        has_required_permissions = has_one_of_permissions(
            requestor, ALL_PRODUCTS_PERMISSIONS
        )
        if channel is None and not has_required_permissions:
            channel = get_default_channel_slug_or_graphql_error()
        #TODO: use token instead
        user = info.context.user
        database_connection_name = get_database_connection_name(info.context)
        qs = (
            product_models.Product.objects.all()
            .using(database_connection_name)
            .visible_to_user(requestor, channel)
        )
        if not has_one_of_permissions(requestor, ALL_PRODUCTS_PERMISSIONS):
            channels = Channel.objects.filter(slug=str(channel))
            product_channel_listings = product_models.ProductChannelListing.objects.filter(
                Exists(channels.filter(pk=OuterRef("channel_id"))),
                visible_in_listings=True,
            )
            qs = qs.filter(
                Exists(product_channel_listings.filter(product_id=OuterRef("pk")))
            )
        qs = ChannelQsContext(qs=qs, channel_slug=channel)

        kwargs["channel"] = channel
        print(kwargs)
        # TODO: same treatment in resolve_products
        if "filter" in kwargs:
            if "attributes" in kwargs["filter"]:
                kwargs["filter"]["attributes"] = [
                    attr for attr in kwargs["filter"]["attributes"] if len(attr["values"]) > 0
                ]
        qs = filter_connection_queryset(qs, kwargs)

        if "filter" in kwargs and "ids" in kwargs["filter"]:
            # follow the 'original' approach as in resolve_products
            print("inside first loop")
            return create_connection_slice(qs, info, kwargs, ProductWPreferenceCountableConnection)
        else:
            print("in second loop")
            #TODO: product should also have a cluster
            import time
            t1 = time.time()
            def softmax(x, T=1):
                x = np.array(x)/T
                max_x = np.max(x)
                exp_x = np.exp(x - max_x)
                sum_exp_x = np.sum(exp_x)
                sm_x = exp_x/sum_exp_x
                return sm_x
            n = kwargs["first"]
            queryset = qs.qs
            print("A", queryset.values_list("id", flat=True))
            product_preference = models.ProductPreference.objects.get(user=user)
            product_colors = (
                models.ProductColor.objects
                .filter(product_id__in=list(queryset.values_list("id", flat=True)))
                .exclude(cluster__isnull=True)
            )
            t2 = time.time()
            print("pc", product_colors, t2-t1)
            clusters = list(product_colors.values_list("cluster", flat=True).distinct())
            t3 = time.time()
            print("c", clusters, t3-t2)
            user_scores = models.ProductColorScore.objects.filter(
                product_score__product_preference = product_preference,
                product_color__in = product_colors
            )
            t4 = time.time()
            print("us", user_scores, t4-t3)
            df = pd.DataFrame.from_records(
                user_scores.values_list("product_color__cluster", "score", "product_color__product_id")
            )
            t5 = time.time()
            print(len(df), "len(df)", t5-t4)
            if len(df) > 0:
                df_groupby = df.groupby(0).agg({1: lambda x: np.mean(np.exp(x))})
                df_groupby = df_groupby.reindex(index=clusters).reset_index()
                c_total_score = np.array(df_groupby[1])

                # Convert cluster score to probabilities
                c_probs_spike = softmax(c_total_score, 0.1)
                c_probs_smooth = softmax(c_total_score, 10)

                # Try sampling up to 3n times
                # Sample 60% of the clusters using softmax with temp = 0.1 and remaining with temp = 10
                n_probs_spike = sum(np.random.rand(3*n) < 0.6)
                n_probs_smooth = 3*n - n_probs_spike
                rng = np.random.default_rng()
                c1 = rng.choice(clusters, size=n_probs_spike, replace=True, p=c_probs_spike)
                c2 = rng.choice(clusters, size=n_probs_smooth, replace=True, p=c_probs_smooth)
                sampled_clusters = np.concatenate([c1,c2])
                rng.shuffle(sampled_clusters)

                # Sample from each cluster
                product_samples = []
                for c in sampled_clusters:
                    if len(product_samples) == n:
                        break
                    df_c = df[(df[0] == c)]
                    df_c = df_c[~df_c[2].isin(product_samples)]
                    if len(df_c) == 0:
                        continue

                    product_pks = df_c[2]
                    colors_probs = softmax(df_c[1])
                    sample = np.random.choice(product_pks, p=colors_probs)
                    product_samples.append(sample)

                products_queryset = product_models.Product.objects.filter(id__in=product_samples)
                matching_records = list(products_queryset)

                edges = [
                    ProductWPreferenceCountableConnection.Edge(
                        node=record,
                        cursor=None,
                    )
                    for record in matching_records
                ]
            else:
                edges = []

            page_info = {
                "has_previous_page": False,
                "has_next_page": False,
                "start_cursor": None,
                "end_cursor": None,
            }
            slice = ProductWPreferenceCountableConnection(
                edges=edges,
                page_info=graphene.relay.PageInfo(**page_info)
            )

            edges_with_context = []
            for edge in slice.edges:
                node = edge.node
                edge.node = ChannelContext(node=node, channel_slug=qs.channel_slug)
                edges_with_context.append(edge)
            slice.edges = edges_with_context
            return slice


    @staticmethod
    @traced_resolver
    def resolve_product_w_preference(
        _root, info: graphene.ResolveInfo, *, id=None, slug=None, channel=None
    ):
        validate_one_of_args_is_in_query("id", id, "slug", slug)
        requestor = get_user_or_app_from_context(info.context)

        has_required_permissions = has_one_of_permissions(
            requestor, ALL_PRODUCTS_PERMISSIONS
        )

        if channel is None and not has_required_permissions:
            channel = get_default_channel_slug_or_graphql_error()

        database_connection_name = get_database_connection_name(info.context)
        qs = models.Product.objects.using(database_connection_name).visible_to_user(
            requestor, channel_slug=channel
        )
        if id:
            _type, id = from_global_id_or_error(id, ProductWPreference)
            product = qs.filter(id=id).first()
        else:
            product = qs.filter(slug=slug).first()
        return ChannelContext(node=product, channel_slug=channel) if product else None



class PreferenceMutations(graphene.ObjectType):
    product_color_bulk_preference_update = ProductColorBulkPreferenceUpdate.Field()