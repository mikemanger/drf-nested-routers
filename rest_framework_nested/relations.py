"""
Serializer fields that deal with relationships with nested resources.

These fields allow you to specify the style that should be used to represent
model relationships with hyperlinks.
"""
from __future__ import annotations

from functools import reduce
from typing import Any, Generic, TypeVar

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Model
from rest_framework.relations import HyperlinkedRelatedField, ObjectTypeError, ObjectValueError
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request


T_Model = TypeVar('T_Model', bound=Model)


class NestedHyperlinkedRelatedField(HyperlinkedRelatedField, Generic[T_Model]):
    lookup_field = 'pk'
    parent_lookup_kwargs = {
        'parent_pk': 'parent__pk'
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.parent_lookup_kwargs = kwargs.pop('parent_lookup_kwargs', self.parent_lookup_kwargs)
        super().__init__(*args, **kwargs)

    def get_url(self, obj: Model, view_name: str, request: Request, format: str | None) -> str | None:
        """
        Given an object, return the URL that hyperlinks to the object.

        May raise a `NoReverseMatch` if the `view_name` and `lookup_field`
        attributes are not configured to correctly match the URL conf.
        """
        # Unsaved objects will not yet have a valid URL.
        if hasattr(obj, 'pk') and obj.pk in (None, ''):
            return None

        # default lookup from rest_framework.relations.HyperlinkedRelatedField
        lookup_value = getattr(obj, self.lookup_field)
        kwargs = {self.lookup_url_kwarg: lookup_value}

        # multi-level lookup
        for parent_lookup_kwarg in list(self.parent_lookup_kwargs.keys()):
            underscored_lookup = self.parent_lookup_kwargs[parent_lookup_kwarg]

            # split each lookup by their __, e.g. "parent__pk" will be split into "parent" and "pk", or
            # "parent__super__pk" would be split into "parent", "super" and "pk"
            lookups = underscored_lookup.split('__')

            try:
                # use the Django ORM to lookup this value, e.g., obj.parent.pk
                lookup_value = reduce(getattr, [obj] + lookups)  # type: ignore[operator,arg-type]
            except AttributeError:
                # Not nested. Act like a standard HyperlinkedRelatedField
                return super().get_url(obj, view_name, request, format)

            # store the lookup_name and value in kwargs, which is later passed to the reverse method
            kwargs.update({parent_lookup_kwarg: lookup_value})

        return self.reverse(view_name, kwargs=kwargs, request=request, format=format)

    def get_object(self, view_name: str, view_args: list[Any], view_kwargs: dict[str, Any]) -> T_Model:
        """
        Return the object corresponding to a matched URL.

        Takes the matched URL conf arguments, and should return an
        object instance, or raise an `ObjectDoesNotExist` exception.
        """
        # default lookup from rest_framework.relations.HyperlinkedRelatedField
        lookup_value = view_kwargs[self.lookup_url_kwarg]
        kwargs = {self.lookup_url_kwarg: lookup_value}

        # multi-level lookup
        for parent_lookup_kwarg in list(self.parent_lookup_kwargs.keys()):
            lookup_value = view_kwargs[parent_lookup_kwarg]
            kwargs.update({self.parent_lookup_kwargs[parent_lookup_kwarg]: lookup_value})

        return self.get_queryset().get(**kwargs)

    def use_pk_only_optimization(self) -> bool:
        return False

    def to_internal_value(self, data: Any) -> T_Model:
        try:
            return super().to_internal_value(data)
        except ValidationError as err:
            if err.detail[0].code != 'no_match':  # type: ignore[union-attr,index]
                raise

            # data is probable the lookup value, not the resource URL
            try:
                return self.get_queryset().get(**{self.lookup_field: data})
            except (ObjectDoesNotExist, ObjectValueError, ObjectTypeError):
                self.fail('does_not_exist')


class NestedHyperlinkedIdentityField(NestedHyperlinkedRelatedField[T_Model]):
    def __init__(self, view_name: str | None = None, **kwargs: Any) -> None:
        assert view_name is not None, 'The `view_name` argument is required.'
        kwargs['read_only'] = True
        kwargs['source'] = '*'
        super().__init__(view_name=view_name, **kwargs)
