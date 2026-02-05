from django.urls import path
from . import views

urlpatterns = [
    path("entradas/", views.entry_bathrooms_view, name="bathroom_entries_list"),
    path("entradas/registrar/<int:fee_id>/", views.entry_bathroom_register_view, name="bathroom_entry_register"),
    path("tarifas/", views.fee_list_view, name="bathroom_fees_list"),
    path("tarifas/registrar/", views.fee_register_view, name="bathroom_fee_register"),
    path("tarifas/editar/<int:fee_id>/", views.fee_edit_view, name="bathroom_fee_edit"),
    path("tarifas/estado/<int:fee_id>/", views.toggle_fee_state_view, name="bathroom_fee_toggle_state"),
]