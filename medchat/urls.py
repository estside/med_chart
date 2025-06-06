from django.urls import path
from .views import doctor_chat_view
from .views import download_chat_pdf



urlpatterns = [
    path("", doctor_chat_view, name="doctor-chat"),
    path('download_chat_pdf/', download_chat_pdf, name='download_chat_pdf'),
]
