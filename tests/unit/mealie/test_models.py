from uuid import uuid4

import pytest
from django.db import models

from cookistash.mealie.models import ModelMealieApi, Source

pytestmark = pytest.mark.django_db


class TestModelMealieApi:
    @pytest.fixture
    def concrete_model(self, django_db_blocker):
        """
        Dynamically create a temporary concrete subclass of ModelMealieApi.
        Django requires a managed model for ORM operations.
        """
        with django_db_blocker.unblock():

            class ConcreteModel(ModelMealieApi):
                id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
                name = models.CharField(max_length=255)
                unit_ref = models.CharField(max_length=255, blank=True, null=True)
                ingredient_notation = models.CharField(max_length=255, blank=True, null=True)

                class Meta:
                    app_label = "testapp"
                    managed = True

            # Create table manually for this transient model
            from django.db import connection

            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(ConcreteModel)

            yield ConcreteModel

            # Drop the table after the test
            with connection.schema_editor() as schema_editor:
                schema_editor.delete_model(ConcreteModel)

    @pytest.fixture
    def api_data(self):
        return {
            "id": str(uuid4()),
            "name": "Parmesan cheese",
            "unit_Ref": "1092-unit-rdpf3",
            "ingredientNotation": "Grated cheese",
        }

    def test_get_or_create_from_api_data_creates(self, concrete_model, api_data):
        obj, created = concrete_model.get_or_create_from_api_data(api_data)

        assert created is True
        assert obj.name == "Parmesan cheese"
        assert obj.unit_ref == "1092-unit-rdpf3"
        assert obj.ingredient_notation == "Grated cheese"
        assert concrete_model.objects.count() == 1

    def test_get_or_create_from_api_data_gets(self, concrete_model, api_data):
        existing = concrete_model.objects.create(
            name=api_data["name"], unit_ref=api_data["unit_Ref"], ingredient_notation=api_data["ingredientNotation"]
        )

        obj, created = concrete_model.get_or_create_from_api_data(api_data)

        assert created is False
        assert obj.id == existing.id
        assert concrete_model.objects.count() == 1

    def test_get_or_create_from_api_data_ignores_invalid_fields(self, concrete_model, api_data):
        bad_data = {**api_data, "extraField": "should be ignored"}

        obj, created = concrete_model.get_or_create_from_api_data(bad_data)

        assert created is True
        assert not hasattr(obj, "extraField") or not hasattr(obj, "extra_field")
        assert obj.name == "Parmesan cheese"

    def test_to_api_data_converts_to_camelcase(self, concrete_model):
        obj = concrete_model.objects.create(
            name="Parmesan cheese",
            unit_ref="1092-unit-rdpf3",
            ingredient_notation="Grated cheese",
        )

        data = obj.to_api_data()

        assert "id" in data
        assert data["id"] == str(obj.id)
        assert data["unitRef"] == "1092-unit-rdpf3"
        assert data["ingredientNotation"] == "Grated cheese"
        assert data["name"] == "Parmesan cheese"


class TestSource:
    def test_create_source(self):
        source = Source.objects.create(
            name="Mealie", api_url="https://example.com", api_token="verysecrettoken", is_default=True
        )
        assert source.pk is not None
        assert str(source) == "Mealie"
        assert source.is_default is True

    def test_only_one_default_with_three_sources(self):
        url = "https://mealie.example.com"
        token = "verysecrettoken"

        s1 = Source.objects.create(name="Source 1", api_url=url, api_token=token, is_default=True)
        assert s1.is_default is True

        s2 = Source.objects.create(name="Source 2", api_url=url, api_token=token, is_default=True)
        s1.refresh_from_db()
        assert s1.is_default is False
        assert s2.is_default is True

        s3 = Source.objects.create(name="Source 3", api_url=url, api_token=token, is_default=True)
        s1.refresh_from_db()
        s2.refresh_from_db()
        assert s1.is_default is False
        assert s2.is_default is False
        assert s3.is_default is True

    @pytest.mark.parametrize("name, is_default", [("s1", False), ("s2", True)])
    def test_auto_default_if_none(self, name, is_default):
        source = Source.objects.create(
            name=name, api_url="https://example.com", api_token="verysecrettoken", is_default=is_default
        )
        assert source.pk is not None
        assert str(source) == name
        assert source.is_default is True
