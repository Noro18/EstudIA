import pytest
from django.db import IntegrityError

from apps.qa.models import StudyQuestion
from apps.qa.tests.factories import StudyQuestionFactory

pytestmark = pytest.mark.django_db


def test_create_study_question_defaults():
    study_question = StudyQuestionFactory(page=7)

    assert study_question.pk is not None
    assert study_question.document_id is not None
    assert study_question.question and study_question.answer
    assert list(study_question.document.study_questions.all()) == [study_question]


def test_duplicate_document_order_is_rejected():
    study_question = StudyQuestionFactory(order=1)

    with pytest.raises(IntegrityError):
        StudyQuestionFactory(document=study_question.document, order=1)


def test_same_order_is_allowed_across_documents():
    first = StudyQuestionFactory(order=1)
    second = StudyQuestionFactory(order=1)

    assert first.order == second.order == 1
    assert first.document_id != second.document_id


def test_deleting_document_cascades_to_study_questions():
    study_question = StudyQuestionFactory()
    document = study_question.document

    document.delete()

    assert StudyQuestion.objects.count() == 0


def test_str_is_readable():
    study_question = StudyQuestionFactory(order=2)

    assert str(study_question).startswith("Study question #2")
