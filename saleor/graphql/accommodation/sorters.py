import graphene

from ..core.types.sort_input import SortInputObjectType

class AccommodationOrderField(graphene.Enum):
    NAME = ["name"]
    SIMILARITY = ["similarity", "name"]

    @property
    def description(self):
        descriptions = {
            AccommodationOrderField.NAME.name: {"name."},
            AccommodationOrderField.SIMILARITY.name: {
                "similarity. Note: This option is available only with the `searchQuery` filter."
            }
        }
        if self.name in descriptions:
            return f"Sort accommodations by {descriptions[self.name]}"
        raise ValueError(f"Unsupported enum value: {self.value}")

class AccommodationOrder(SortInputObjectType):
    field = graphene.Argument(
        AccommodationOrderField, description="Sort accommodations by the selected field."
    )

    class Meta:
        sort_enum = AccommodationOrderField