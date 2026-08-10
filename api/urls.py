from django.urls import path

from . import views


urlpatterns = [
    path("index/", views.index, name="index"),
    path("oauth/", views.auth_return, name="oauth"),
    path("documents/", views.list_documents, name="list_documents"),
    path("document/<str:doc_id>/", views.get_document, name="get_document"),
]
