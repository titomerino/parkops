from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.timezone import now, localtime
from django.shortcuts import redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from shell.decorators import perm_required

from .models import BathroomFee, BathroomEntry
from .forms import BathroomFeeForm


@perm_required('bathrooms.view_bathroomfee')
def fee_list_view(request):
    """ Página de listado de tarifas de baño """

    fees = BathroomFee.objects.all().order_by('-id')

    return render(request, "fee_list.html", {
        'fees': fees
    })

@perm_required('bathrooms.view_bathroomentry')
def entry_bathrooms_view(request):
    """ Página de entradas al baño del dia """

    today = localtime(now()).date()

    entries = BathroomEntry.objects.filter(
        entry_date_hour__date=today
    ).order_by('-entry_date_hour')

    fees = BathroomFee.objects.all().filter(state=True)

    return render(request, "entry_bathrooms.html", {
        'entries': entries,
        'today': today,
        'fees': fees
    })

@require_POST
@perm_required('bathrooms.add_bathroomentry')
def entry_bathroom_register_view(request, fee_id):
    """ Vista para registrar una entrada de baño """
    fee = BathroomFee.objects.get(id=fee_id)

    # Crear entrada de baño
    bathroom_entry = BathroomEntry.objects.create(
        fee=fee
    )
    bathroom_entry.save()
    messages.success(
        request,
        f"El acceso para {bathroom_entry.fee.name} se guardó correctamente."
    )

    return redirect('bathroom_entries_list')

@perm_required('bathrooms.add_bathroomfee')
def fee_register_view(request):
    """ Vista para registrar una tarifa de baño """

    if request.method == 'POST':
        form = BathroomFeeForm(request.POST)
        if form.is_valid():
            bathroom_fee = form.save()
            messages.success(
                request,
                f"La tarifa {bathroom_fee.name} se guardó correctamente."
            )
            return redirect('bathroom_fees_list')
    else:
        form = BathroomFeeForm()

    return render(request, "fee_register.html", {
        'form': form,
    })

@perm_required('bathrooms.change_bathroomfee')
def fee_edit_view(request, fee_id):
    """ Vista para editar una tarifa de baño """
    bathroom_fee = BathroomFee.objects.get(id=fee_id)

    if request.method == 'POST':
        form = BathroomFeeForm(request.POST, instance=bathroom_fee)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f"La tarifa {bathroom_fee.name} se actualizó correctamente."
            )
            return redirect('bathroom_fees_list')
    else:
        form = BathroomFeeForm(instance=bathroom_fee)
        if BathroomEntry.objects.filter(fee=bathroom_fee).exists():
            form.fields['name'].disabled = True
            form.fields['amount'].disabled = True

    return render(request, "fee_register.html", {
        'form': form,
        'is_edit': True,
        'bathroom_fee': bathroom_fee
    })

@require_POST
@perm_required('bathrooms.change_bathroomfee')
def toggle_fee_state_view(request, fee_id):
    """ Vista para activar/desactivar una tarifa de baño """
    bathroom_fee = BathroomFee.objects.get(id=fee_id)
    bathroom_fee.state = not bathroom_fee.state
    bathroom_fee.save()
    state_text = "activada" if bathroom_fee.state else "desactivada"
    messages.success(
        request,
        f"La tarifa {bathroom_fee.name} ha sido {state_text} correctamente."
    )
    return redirect('bathroom_fees_list')

