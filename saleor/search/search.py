import requests
from django.conf import settings

search_uri = settings.SEARCH_URI

def get_scores_update_old(product_color_ids):
    # TODO: if request fail
    json = [{'pk': i} for i in product_color_ids]
    response = requests.post(url=search_uri, json=json)
    if response.status_code == 200:
        data = response.json()
        scores_delta = data['delta']
        color_ids = data['pk']
        return scores_delta, color_ids
    else:
        raise ValueError("Response error")

def get_scores_update(disliked_product_color_ids, neutral_product_color_ids):
    # TODO: if request fail
    json = {
        'disliked_product_colors':[{'pk': i} for i in disliked_product_color_ids],
        'neutral_product_colors':[{'pk': i} for i in neutral_product_color_ids]
    }
    response = requests.post(url=search_uri, json=json)
    if response.status_code == 200:
        data = response.json()
        disliked_delta = data['disliked_delta']
        disliked_ids = data['disliked_pk']
        neutral_delta = data['neutral_delta']
        neutral_ids = data['neutral_pk']

        return disliked_delta, disliked_ids, neutral_delta, neutral_ids
    else:
        raise ValueError("Response error")