from ..product.dataloaders.products import BaseThumbnailBySizeAndFormatLoader

class ThumbnailByAccommodationIdSizeAndFormatLoader(BaseThumbnailBySizeAndFormatLoader):
    context_key = "thumbnail_by_accommodation_size_and_format"
    model_name = "accommodation"