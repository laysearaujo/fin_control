from django.shortcuts import get_object_or_404


def get_owned_or_404(request, Model, **kwargs):
    """Fetches an object by PK (or any other lookup) scoped to the current user -
    the single choke point that stops one user from reading/editing/deleting another
    user's object by guessing its id in a URL."""
    return get_object_or_404(Model.objects.for_user(request.user), **kwargs)
