import django_filters
import graphene
from django.db import models
from ..core.filters import MetadataFilterBase
from ..core.types.filter_input import FilterInputObjectType

class TrigramWordSimilarity(models.Func):
    function = "WORD_SIMILARITY"
    output_field = models.FloatField()

    def __init__(self, string, expression, **extra):
        if not hasattr(string, "resolve_expression"):
            string = models.Value(string)
        super().__init__(string, expression, **extra)

def filter_search(qs, _, value):
    print("here filter_search", value)
    print(len(qs))
    if value:
        qs = qs.annotate(
            similarity=TrigramWordSimilarity(value, "name"),
        ).filter(
            similarity__gt=0.4
        )
        print("filtered", len(qs))
    return qs


class AccommodationFilter(MetadataFilterBase):
    search_query = django_filters.CharFilter(method=filter_search)

class AccommodationFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = AccommodationFilter