"""Local FAISS retrieval service for Telosia knowledge."""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer


load_dotenv()


ROOT = Path(__file__).resolve().parents[2]

DEFAULT_RAG_DIRECTORY = ROOT / "knowledge" / "rag"

DEFAULT_TOP_K = 5
DEFAULT_MINIMUM_SCORE = 0.30
MAXIMUM_TOP_K = 10


# Common user terms mapped to TOOCS bodily location codes.
BODY_PART_ALIASES: dict[str, set[str]] = {
    "110": {"head", "skull", "cranium"},
    "111": {"brain"},
    "120": {"eye", "eyes", "eyeball"},
    "121": {"eyelid", "ocular"},
    "130": {"ear", "ears", "hearing"},
    "160": {"face", "facial"},
    "210": {"neck", "cervical"},
    "310": {"upper back", "thoracic back"},
    "311": {
        "lower back",
        "low back",
        "lumbar",
        "lumbar spine",
    },
    "330": {"rib", "ribs", "chest wall"},
    "346": {"pelvis", "pelvic"},
    "410": {"shoulder", "shoulders"},
    "420": {"upper arm", "upper arms"},
    "430": {"elbow", "elbows"},
    "440": {"forearm", "forearms"},
    "450": {"wrist", "wrists"},
    "460": {"hand", "hands"},
    "461": {"finger", "fingers"},
    "462": {"thumb", "thumbs"},
    "510": {"hip", "hips"},
    "520": {"upper leg", "thigh", "thighs"},
    "530": {"knee", "knees"},
    "540": {"lower leg", "shin", "shins"},
    "550": {"ankle", "ankles"},
    "560": {"foot", "feet"},
    "710": {"circulatory", "circulation"},
    "720": {"respiratory", "breathing", "lung", "lungs"},
    "750": {"nervous system", "neurological"},
    "800": {
        "psychological",
        "mental health",
        "psychosocial",
    },
}


class RagConfigurationError(RuntimeError):
    """Raised when the local RAG files are missing or inconsistent."""


def _calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)

    return digest.hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    documents = []

    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                document = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RagConfigurationError(
                    f"Invalid JSON on line {line_number} "
                    f"of {path.name}."
                ) from exc

            documents.append(document)

    return documents


def _normalise_query(query: str) -> str:
    return " ".join(query.lower().strip().split())


def _detect_body_codes(query: str) -> set[str]:
    """Recognise explicit body-part terms in the user's question."""

    normalised_query = _normalise_query(query)
    matched_codes = set()

    for body_code, aliases in BODY_PART_ALIASES.items():
        if any(alias in normalised_query for alias in aliases):
            matched_codes.add(body_code)

    return matched_codes


def _document_body_codes(document: dict[str, Any]) -> set[str]:
    metadata = document.get("metadata", {})
    body_codes = set()

    single_body_code = metadata.get("body_code")
    if single_body_code:
        body_codes.add(str(single_body_code))

    for body_code in metadata.get("body_codes", []):
        body_codes.add(str(body_code))

    return body_codes


def _status_is_allowed(
    document: dict[str, Any],
    allow_unreviewed: bool,
) -> bool:
    document_type = document.get("document_type")
    metadata = document.get("metadata", {})

    if document_type == "methodology":
        return True

    if document_type == "hazard_body_association":
        status = metadata.get("review_status", "")
        return status == "approved" or (
            allow_unreviewed
            and status == "needs_human_review"
        )

    if document_type == "body_part_hazards":
        related_hazards = metadata.get(
            "related_hazards",
            [],
        )

        return any(
            hazard.get("review_status") == "approved"
            or (
                allow_unreviewed
                and hazard.get("review_status")
                == "needs_human_review"
            )
            for hazard in related_hazards
        )

    return False


def _filtered_metadata(
    document: dict[str, Any],
    allow_unreviewed: bool,
) -> dict[str, Any]:
    """Remove unapproved nested hazard records in production mode."""

    metadata = dict(document.get("metadata", {}))

    if (
        document.get("document_type") == "body_part_hazards"
        and not allow_unreviewed
    ):
        metadata["related_hazards"] = [
            hazard
            for hazard in metadata.get("related_hazards", [])
            if hazard.get("review_status") == "approved"
        ]

    return metadata


class RagRetriever:
    """Load and search the local Telosia FAISS index."""

    def __init__(
        self,
        rag_directory: Path | None = None,
    ) -> None:
        configured_directory = os.getenv("RAG_INDEX_DIRECTORY")

        if rag_directory is not None:
            self.rag_directory = rag_directory
        elif configured_directory:
            self.rag_directory = Path(configured_directory)
        else:
            self.rag_directory = DEFAULT_RAG_DIRECTORY

        self.documents_file = (
            self.rag_directory / "documents.jsonl"
        )
        self.index_file = self.rag_directory / "index.faiss"
        self.manifest_file = (
            self.rag_directory / "manifest.json"
        )

        self.allow_unreviewed = (
            os.getenv(
                "RAG_ALLOW_UNREVIEWED",
                "false",
            ).lower()
            in {"1", "true", "yes"}
        )

        self.minimum_score = float(
            os.getenv(
                "RAG_MINIMUM_SCORE",
                str(DEFAULT_MINIMUM_SCORE),
            )
        )

        self._validate_files_exist()

        self.manifest = json.loads(
            self.manifest_file.read_text(encoding="utf-8")
        )
        self.documents = _load_jsonl(self.documents_file)
        self.index = faiss.read_index(str(self.index_file))

        self._validate_index()

        self.model = SentenceTransformer(
            self.manifest["embedding_model"]
        )

    def _validate_files_exist(self) -> None:
        required_files = [
            self.documents_file,
            self.index_file,
            self.manifest_file,
        ]

        missing = [
            str(path)
            for path in required_files
            if not path.exists()
        ]

        if missing:
            raise RagConfigurationError(
                "Missing RAG files: " + ", ".join(missing)
            )

    def _validate_index(self) -> None:
        expected_hash = self.manifest.get(
            "documents_sha256"
        )
        actual_hash = _calculate_sha256(
            self.documents_file
        )

        if expected_hash != actual_hash:
            raise RagConfigurationError(
                "documents.jsonl has changed since the "
                "FAISS index was generated. Rebuild the index."
            )

        manifest_chunk_ids = self.manifest.get(
            "chunk_ids",
            [],
        )
        document_chunk_ids = [
            document["chunk_id"]
            for document in self.documents
        ]

        if manifest_chunk_ids != document_chunk_ids:
            raise RagConfigurationError(
                "Document order does not match manifest.json."
            )

        document_count = len(self.documents)
        manifest_count = int(
            self.manifest["vector_count"]
        )

        if not (
            self.index.ntotal
            == document_count
            == manifest_count
        ):
            raise RagConfigurationError(
                "FAISS vector count, document count, and "
                "manifest count do not match."
            )

        expected_dimension = int(
            self.manifest["vector_dimension"]
        )

        if self.index.d != expected_dimension:
            raise RagConfigurationError(
                "FAISS vector dimension does not match "
                "manifest.json."
            )

    def search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        minimum_score: float | None = None,
    ) -> list[dict[str, Any]]:
        query = query.strip()

        if not query:
            return []

        if not 1 <= top_k <= MAXIMUM_TOP_K:
            raise ValueError(
                f"top_k must be between 1 and "
                f"{MAXIMUM_TOP_K}."
            )

        score_threshold = (
            self.minimum_score
            if minimum_score is None
            else minimum_score
        )

        matched_body_codes = _detect_body_codes(query)

        query_embedding = self.model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

        query_embedding = np.asarray(
            query_embedding,
            dtype=np.float32,
        )

        # FAISS itself does not filter metadata. When a body part is
        # recognised, search the whole small index and filter afterwards.
        if matched_body_codes:
            candidate_count = self.index.ntotal
        else:
            candidate_count = min(
                self.index.ntotal,
                max(top_k * 5, 20),
            )

        scores, positions = self.index.search(
            query_embedding,
            candidate_count,
        )

        results = []
        seen_keys = set()

        for score, position in zip(
            scores[0],
            positions[0],
        ):
            if position < 0:
                continue

            numeric_score = float(score)

            if numeric_score < score_threshold:
                continue

            document = self.documents[int(position)]

            if not _status_is_allowed(
                document,
                self.allow_unreviewed,
            ):
                continue

            if matched_body_codes:
                document_codes = _document_body_codes(
                    document
                )

                if not (
                    document_codes
                    & matched_body_codes
                ):
                    continue

            metadata = _filtered_metadata(
                document,
                self.allow_unreviewed,
            )

            if (
                document["document_type"]
                == "hazard_body_association"
            ):
                deduplication_key = (
                    "hazard",
                    metadata["hazard_variable_id"],
                )
            else:
                deduplication_key = (
                    "chunk",
                    document["chunk_id"],
                )

            if deduplication_key in seen_keys:
                continue

            seen_keys.add(deduplication_key)

            results.append(
                {
                    "chunk_id": document["chunk_id"],
                    "document_type": document[
                        "document_type"
                    ],
                    "similarity_score": round(
                        numeric_score,
                        4,
                    ),
                    "text": document["text"],
                    "metadata": metadata,
                }
            )

            if len(results) >= top_k:
                break

        return results


@lru_cache(maxsize=1)
def get_rag_retriever() -> RagRetriever:
    """Load the model and index once per backend process."""

    return RagRetriever()


def retrieve_knowledge(
    question: str,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """Public helper used by the chatbot context service."""

    return get_rag_retriever().search(
        query=question,
        top_k=top_k,
    )
