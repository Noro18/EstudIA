from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.documents import views as document_views
from apps.qa import views as qa_views

urlpatterns = [
    path("", RedirectView.as_view(url="/notebooks/", permanent=False), name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("notebooks/", document_views.notebook_list, name="notebook_list"),
    path("notebooks/<int:pk>/", document_views.notebook_workspace, name="notebook_workspace"),
    path("notebooks/<int:pk>/documents/", document_views.notebook_upload_document, name="notebook_upload_document"),
    path("notebooks/<int:pk>/ask/", qa_views.notebook_ask, name="notebook_ask"),
    path("notebooks/<int:pk>/quiz/", qa_views.notebook_quiz_start, name="notebook_quiz_start"),
    path("notebooks/<int:pk>/quiz/submit/", qa_views.notebook_quiz_submit, name="notebook_quiz_submit"),
    path("documents/<int:pk>/", document_views.document_detail, name="document_detail"),
    path("conversations/<int:pk>/", qa_views.conversation_detail, name="conversation_detail"),
]