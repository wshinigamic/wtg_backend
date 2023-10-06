from django.db import models
from ..account.models import Address
from ..core.models import ModelWithMetadata

class TrigramWordSimilarity(models.Func):
    function = "WORD_SIMILARITY"
    output_field = models.FloatField()

    def __init__(self, string, expression, **extra):
        if not hasattr(string, "resolve_expression"):
            string = models.Value(string)
        super().__init__(string, expression, **extra)

class AccommodationQuerySet(models.QuerySet):
    def search_by_name(self, searchQuery):
        return self.annotate(
            similarity=TrigramWordSimilarity(searchQuery, "name"),
        ).filter(
            similarity__gt=0.4
        ).order_by("-similarity")

class Accommodation(ModelWithMetadata):
    # TODO: Set permission: only superadmin can create accommodation
    name = models.CharField(max_length=256, unique=True)
    logo_image = models.ImageField(
        upload_to="accommodation-logos", blank=True, null=True
    )
    address = models.ForeignKey(Address, on_delete=models.PROTECT)
    website_url = models.URLField(blank=True, null=True)
    isActive = models.BooleanField(default=False)

    objects = models.Manager.from_queryset(AccommodationQuerySet)()