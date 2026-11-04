import math

import pytest
from django.conf import settings

from apps.rag.embeddings import embed_query


def test_query_embedding_is_normalized_and_matches_configured_dimension():
    vector = embed_query("Saida mak ideia prinsipál husi dokumentu ne'e?")

    assert len(vector) == settings.EMBEDDING_DIM
    assert all(math.isfinite(float(value)) for value in vector)

    norm = math.sqrt(sum(float(value) ** 2 for value in vector))
    assert norm == pytest.approx(1.0, abs=1e-5)
