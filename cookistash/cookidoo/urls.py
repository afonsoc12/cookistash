from django.urls import path

from . import views

app_name = "cookidoo"

urlpatterns = [
    path("", views.recipe_list, name="recipe_list"),
    path("discover/", views.discover, name="discover"),
    path("discover/<str:recipe_id>/import/", views.discover_import, name="discover_import"),
    path("scrape/", views.recipe_scrape_new, name="recipe_scrape_new"),
    path("<str:recipe_id>/", views.recipe_detail, name="recipe_detail"),
    path("<str:recipe_id>/rescrape/", views.recipe_rescrape, name="recipe_rescrape"),
    path("<str:recipe_id>/send-to-mealie/", views.recipe_send_to_mealie, name="recipe_send_to_mealie"),
]
