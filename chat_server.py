#!/usr/bin/env python3
"""
Chat Server — RAG Chat Interface with V2 Strategy
===================================================
Backend API for the chat UI using SectionChunker + Metadata Filtering.

Run: python3 chat_server.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Project imports
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from src.chunking import SectionChunker, RecursiveChunker
from src.embeddings import _mock_embed
from src.models import Document
from src.store import EmbeddingStore
from src.agent import KnowledgeBaseAgent

# ── Configuration ──────────────────────────────────────────────────────────────

HANDBOOK_DIR = project_root / "data" / "handbook"

DOCUMENTS_META = [
    {"file": "bat_dau_lam_viec.md",        "category": "onboarding", "topic": "first_days",       "label": "Bắt Đầu Làm Việc"},
    {"file": "cach_lam_viec.md",           "category": "work_culture", "topic": "remote_async",   "label": "Cách Làm Việc"},
    {"file": "he_thong_noi_bo.md",         "category": "tools", "topic": "internal_systems",      "label": "Hệ Thống Nội Bộ"},
    {"file": "lam_them_ngoai_gio.md",      "category": "policy", "topic": "moonlighting",        "label": "Làm Thêm Ngoài Giờ"},
    {"file": "nghi_le_va_truyen_thong.md", "category": "culture", "topic": "traditions",          "label": "Nghỉ Lễ & Truyền Thống"},
    {"file": "nghi_viec_va_tro_cap.md",    "category": "policy", "topic": "severance",            "label": "Nghỉ Việc & Trợ Cấp"},
    {"file": "phat_trien_nghe_nghiep.md",  "category": "career", "topic": "promotion",            "label": "Phát Triển Nghề Nghiệp"},
    {"file": "phuc_loi_va_quyen_loi.md",   "category": "benefits", "topic": "insurance_pto",      "label": "Phúc Lợi & Quyền Lợi"},
    {"file": "quan_ly_thiet_bi.md",        "category": "tools", "topic": "device_security",       "label": "Quản Lý Thiết Bị"},
]

# Category → human-readable label + icon mapping
CATEGORY_INFO = {
    "onboarding":   {"label": "Onboarding",       "icon": "🚀", "color": "#6366f1"},
    "work_culture": {"label": "Văn Hóa Làm Việc", "icon": "🏢", "color": "#8b5cf6"},
    "tools":        {"label": "Công Cụ & Hệ Thống", "icon": "🔧", "color": "#06b6d4"},
    "policy":       {"label": "Chính Sách",        "icon": "📋", "color": "#f59e0b"},
    "culture":      {"label": "Văn Hóa Công Ty",   "icon": "🎉", "color": "#ec4899"},
    "career":       {"label": "Sự Nghiệp",        "icon": "📈", "color": "#10b981"},
    "benefits":     {"label": "Phúc Lợi",          "icon": "🎁", "color": "#ef4444"},
}

# Simple keyword → category mapping for auto-filtering
CATEGORY_KEYWORDS = {
    "benefits":     ["nghỉ phép", "phúc lợi", "bảo hiểm", "nghỉ lễ", "pto", "sabbatical", "nghỉ hè", "insurance", "benefit"],
    "policy":       ["chính sách", "ngoài giờ", "làm thêm", "moonlighting", "nghỉ việc", "trợ cấp", "severance"],
    "onboarding":   ["nhân viên mới", "tuần đầu", "bắt đầu", "onboarding", "ngày đầu"],
    "career":       ["lương", "thăng chức", "sự nghiệp", "career", "salary", "promotion", "thăng tiến"],
    "tools":        ["hệ thống", "công cụ", "sentry", "basecamp", "tool", "lỗi", "bug", "thiết bị"],
    "work_culture": ["làm việc", "remote", "từ xa", "giao tiếp", "async"],
    "culture":      ["truyền thống", "lễ", "văn hóa", "tradition"],
}


def detect_category(query: str) -> str | None:
    """Auto-detect the best category for a query based on keywords."""
    query_lower = query.lower()
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            scores[cat] = score
    if scores:
        return max(scores, key=scores.get)
    return None


def keyword_rerank(query: str, results: list[dict], content_key: str = "content") -> list[dict]:
    """Re-rank search results by keyword overlap with the query.
    
    MockEmbedder produces near-random similarity scores, so we boost chunks
    that share more words with the query. This simple heuristic dramatically
    improves relevance for the handbook domain.
    """
    # Extract meaningful keywords from query (>= 2 chars, lowercased)
    query_words = set(w.lower() for w in re.findall(r'\w{2,}', query))
    if not query_words:
        return results

    scored = []
    for r in results:
        text = r.get(content_key, "").lower()
        # Count how many query words appear in the chunk
        overlap = sum(1 for w in query_words if w in text)
        # Bonus for query words appearing in the first line (header)
        first_line = text.split("\n")[0] if text else ""
        header_bonus = sum(2 for w in query_words if w in first_line)
        scored.append((r, overlap + header_bonus))
    
    scored.sort(key=lambda x: x[1], reverse=True)
    return [item[0] for item in scored]


# ── Global state ───────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder="chat_ui")
CORS(app)

# Initialize RAG pipeline
store: EmbeddingStore | None = None
agent: KnowledgeBaseAgent | None = None
loaded_documents: list[Document] = []
chunk_stats: dict = {}


def mock_llm(prompt: str) -> str:
    """Mock LLM: selects the most relevant chunk(s) as the answer.
    
    Since we don't have a real LLM, this function extracts the question,
    then picks the chunk with the highest keyword overlap as the primary answer.
    """
    chunks_text = []
    question = ""
    if "Context:" in prompt:
        context_part = prompt.split("Context:")[1].split("Question:")[0].strip()
        chunk_segments = re.split(r"Chunk \d+:", context_part)
        for seg in chunk_segments:
            seg = seg.strip()
            if seg:
                chunks_text.append(seg)
    
    if "Question:" in prompt:
        question = prompt.split("Question:")[1].split("Answer:")[0].strip()

    if not chunks_text:
        return "Xin lỗi, tôi không tìm thấy thông tin liên quan trong sổ tay nhân viên. Vui lòng thử câu hỏi khác."

    # Rank chunks by keyword overlap with the question
    if question:
        query_words = set(w.lower() for w in re.findall(r'\w{2,}', question))
        scored = []
        for chunk in chunks_text:
            chunk_lower = chunk.lower()
            overlap = sum(1 for w in query_words if w in chunk_lower)
            first_line = chunk.split("\n")[0].lower()
            header_bonus = sum(2 for w in query_words if w in first_line)
            scored.append((chunk, overlap + header_bonus))
        scored.sort(key=lambda x: x[1], reverse=True)
        chunks_text = [s[0] for s in scored]

    # Use the best chunk, add second if short
    answer = chunks_text[0]
    if len(answer) < 400 and len(chunks_text) > 1:
        answer = answer + "\n\n" + chunks_text[1]
    
    if len(answer) > 1500:
        answer = answer[:1500] + "..."

    return answer


def initialize_rag():
    """Load documents, chunk with SectionChunker, and build the store."""
    global store, agent, loaded_documents, chunk_stats

    documents = []
    for meta in DOCUMENTS_META:
        filepath = HANDBOOK_DIR / meta["file"]
        if not filepath.exists():
            continue
        content = filepath.read_text(encoding="utf-8")
        documents.append(
            Document(
                id=filepath.stem,
                content=content,
                metadata={
                    "source": meta["file"],
                    "category": meta["category"],
                    "topic": meta["topic"],
                    "label": meta["label"],
                },
            )
        )
    loaded_documents = documents

    # SectionChunker — V2 strategy
    chunker = SectionChunker(max_section_chars=1000)
    chunked_docs = []
    total_chunks = 0
    doc_chunk_counts = {}

    for doc in documents:
        chunks = chunker.chunk(doc.content)
        total_chunks += len(chunks)
        doc_chunk_counts[doc.id] = len(chunks)
        for i, chunk_text in enumerate(chunks):
            chunked_docs.append(
                Document(
                    id=f"{doc.id}_sec_{i}",
                    content=chunk_text,
                    metadata={**doc.metadata, "chunk_index": str(i)},
                )
            )

    store = EmbeddingStore(collection_name="handbook_chat_v2", embedding_fn=_mock_embed)
    store.add_documents(chunked_docs)
    agent = KnowledgeBaseAgent(store=store, llm_fn=mock_llm)

    chunk_stats = {
        "total_docs": len(documents),
        "total_chunks": total_chunks,
        "doc_chunk_counts": doc_chunk_counts,
        "strategy": "SectionChunker (max_section_chars=1000)",
        "embedder": "MockEmbedder (64-dim, hash-based)",
    }

    print(f"✅ Loaded {len(documents)} documents → {total_chunks} chunks")


# ── API Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("chat_ui", "index.html")


@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory("chat_ui", path)


@app.route("/api/chat", methods=["POST"])
def chat():
    """Main chat endpoint with V2 strategy."""
    data = request.json
    query = data.get("query", "").strip()
    manual_category = data.get("category")  # Optional manual filter

    if not query:
        return jsonify({"error": "Query cannot be empty"}), 400

    start_time = time.time()

    # Auto-detect or use manual category
    category = manual_category or detect_category(query)
    metadata_filter = {"category": category} if category else None

    # Search with filter, then re-rank by keyword overlap
    if metadata_filter:
        search_results = store.search_with_filter(query, top_k=6, metadata_filter=metadata_filter)
        # Normalize key names
        for r in search_results:
            if "text" in r and "content" not in r:
                r["content"] = r["text"]
    else:
        search_results = store.search(query, top_k=6)
    
    # Keyword re-ranking: compensate for MockEmbedder's random scores
    search_results = keyword_rerank(query, search_results)[:3]

    # Build context and get agent answer
    context_chunks = []
    for i, result in enumerate(search_results):
        content = result.get("content", "")
        meta = result.get("metadata", {})
        context_chunks.append({
            "rank": i + 1,
            "content": content,
            "score": round(result.get("score", 0.0), 4),
            "source": meta.get("source", "unknown"),
            "category": meta.get("category", "unknown"),
            "topic": meta.get("topic", "unknown"),
            "label": meta.get("label", ""),
        })

    # Generate answer from the FILTERED search results (not agent.answer which is unfiltered)
    # Build context from the same chunks we display
    if search_results:
        context_parts = []
        for i, result in enumerate(search_results):
            content = result.get("content", "")
            context_parts.append(f"Chunk {i+1}:\n{content}")
        context = "\n\n".join(context_parts)
        prompt = f"Context:\n{context}\n\nQuestion: {query}\nAnswer:"
        answer = mock_llm(prompt)
    else:
        answer = "Xin lỗi, tôi không tìm thấy thông tin liên quan trong sổ tay nhân viên. Vui lòng thử câu hỏi khác."
    elapsed = time.time() - start_time

    # Get category info
    cat_info = CATEGORY_INFO.get(category, {"label": "Tất cả", "icon": "🔍", "color": "#6b7280"})

    return jsonify({
        "answer": answer,
        "query": query,
        "filter_applied": {
            "category": category,
            "label": cat_info["label"],
            "icon": cat_info["icon"],
            "color": cat_info["color"],
        } if category else None,
        "chunks": context_chunks,
        "elapsed_ms": round(elapsed * 1000, 1),
        "strategy": "SectionChunker + Metadata Filtering (V2)",
    })


@app.route("/api/info", methods=["GET"])
def info():
    """Return system info and document stats."""
    docs_info = []
    for doc in loaded_documents:
        cat = doc.metadata.get("category", "")
        cat_info = CATEGORY_INFO.get(cat, {"label": cat, "icon": "📄", "color": "#6b7280"})
        docs_info.append({
            "id": doc.id,
            "label": doc.metadata.get("label", doc.id),
            "source": doc.metadata.get("source", ""),
            "category": cat,
            "category_label": cat_info["label"],
            "category_icon": cat_info["icon"],
            "category_color": cat_info["color"],
            "topic": doc.metadata.get("topic", ""),
            "chunks": chunk_stats.get("doc_chunk_counts", {}).get(doc.id, 0),
            "chars": len(doc.content),
        })

    categories = {}
    for cat, info_data in CATEGORY_INFO.items():
        cat_docs = [d for d in docs_info if d["category"] == cat]
        if cat_docs:
            categories[cat] = {
                **info_data,
                "doc_count": len(cat_docs),
                "total_chunks": sum(d["chunks"] for d in cat_docs),
            }

    return jsonify({
        "strategy": chunk_stats.get("strategy", ""),
        "embedder": chunk_stats.get("embedder", ""),
        "total_docs": chunk_stats.get("total_docs", 0),
        "total_chunks": chunk_stats.get("total_chunks", 0),
        "documents": docs_info,
        "categories": categories,
    })


@app.route("/api/suggestions", methods=["GET"])
def suggestions():
    """Return suggested queries."""
    return jsonify({
        "suggestions": [
            {"query": "Nhân viên được nghỉ phép bao nhiêu ngày mỗi năm?", "icon": "🏖️", "category": "benefits"},
            {"query": "Công ty có chính sách gì về làm thêm ngoài giờ?", "icon": "🌙", "category": "policy"},
            {"query": "Nhân viên mới cần gặp ai trong tuần đầu tiên?", "icon": "👋", "category": "onboarding"},
            {"query": "Mức lương tối thiểu và cách tính lương tại công ty?", "icon": "💰", "category": "career"},
            {"query": "Công ty dùng hệ thống nào để theo dõi lỗi lập trình?", "icon": "🐛", "category": "tools"},
        ]
    })


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🚀 Initializing RAG pipeline (V2: SectionChunker + Metadata Filtering)...")
    initialize_rag()
    print(f"🌐 Starting chat server at http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False)
