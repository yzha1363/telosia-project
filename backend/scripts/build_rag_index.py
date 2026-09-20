from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


ROOT = Path(__file__).resolve().parents[1]

DOCUMENTS_FILE = ROOT / "knowledge" / "rag" / "documents.jsonl"
INDEX_FILE = ROOT / "knowledge" / "rag" / "index.faiss"
MANIFEST_FILE = ROOT / "knowledge" / "rag" / "manifest.json"

MODEL_NAME = os.getenv(
    "RAG_EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)


def load_documents() -> list[dict[str, Any]]:
    if not DOCUMENTS_FILE.exists():
        raise FileNotFoundError(
            f"Knowledge chunks not found: {DOCUMENTS_FILE}"
        )

    documents = []

    with DOCUMENTS_FILE.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            line = line.strip()

            if not line:
                continue

            document = json.loads(line)

            if not document.get("chunk_id"):
                raise ValueError(
                    f"Missing chunk_id on line {line_number}"
                )

            if not document.get("text"):
                raise ValueError(
                    f"Missing text on line {line_number}"
                )

            documents.append(document)

    if not documents:
        raise RuntimeError("No knowledge chunks were found.")

    chunk_ids = [
        document["chunk_id"]
        for document in documents
    ]

    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("Duplicate chunk_id values were found.")

    return documents


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)

    return digest.hexdigest()


def main() -> None:
    documents = load_documents()
    texts = [document["text"] for document in documents]

    print(f"Loading embedding model: {MODEL_NAME}")

    model = SentenceTransformer(MODEL_NAME)

    print(f"Generating vectors for {len(texts)} chunks...")

    embeddings = model.encode(
        texts,
        batch_size=16,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    embeddings = np.asarray(
        embeddings,
        dtype=np.float32,
    )

    if embeddings.ndim != 2:
        raise ValueError(
            f"Expected a two-dimensional vector array, "
            f"received shape {embeddings.shape}"
        )

    vector_dimension = embeddings.shape[1]

    # Normalized vectors + inner product = cosine similarity.
    index = faiss.IndexFlatIP(vector_dimension)
    index.add(embeddings)

    if index.ntotal != len(documents):
        raise RuntimeError(
            "FAISS vector count does not match document count."
        )

    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_FILE))

    manifest = {
        "embedding_model": MODEL_NAME,
        "vector_dimension": vector_dimension,
        "vector_count": int(index.ntotal),
        "index_type": "IndexFlatIP",
        "similarity": "cosine_similarity",
        "normalised_embeddings": True,
        "documents_file": DOCUMENTS_FILE.name,
        "documents_sha256": calculate_sha256(DOCUMENTS_FILE),
        "chunk_ids": [
            document["chunk_id"]
            for document in documents
        ],
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    MANIFEST_FILE.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("Vector index generated successfully.")
    print(f"Documents: {len(documents)}")
    print(f"Vector dimension: {vector_dimension}")
    print(f"FAISS vectors: {index.ntotal}")
    print(f"Index file: {INDEX_FILE}")
    print(f"Manifest file: {MANIFEST_FILE}")


if __name__ == "__main__":
    main()