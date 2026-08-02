from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import render, redirect


@login_not_required
def signup(request):
    """Creates a brand new, fully isolated account - no data is shared with any
    other user (each person's categories, caixinhas, cartões etc. start empty)."""
    form = UserCreationForm(request.POST or None)
    if form.is_valid():
        user = form.save()
        login(request, user)
        return redirect('dashboard')
    return render(request, 'registration/signup.html', {'form': form})
