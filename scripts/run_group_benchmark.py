#!/usr/bin/env python3
"""
Group Benchmark Script — Lab 7: Embedding & Vector Store
=========================================================
Chạy: python scripts/run_group_benchmark.py

Script thực hiện:
1. Load 9 tài liệu handbook với metadata
2. Chạy ChunkingStrategyComparator trên 3 tài liệu đại diện (baseline)
3. Chunk tài liệu bằng RecursiveChunker → add vào EmbeddingStore
4. Chạy 5 benchmark queries → xuất kết quả
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.chunking import (
    ChunkingStrategyComparator,
    RecursiveChunker,
    SentenceChunker,
    FixedSizeChunker,
)
from src.embeddings import _mock_embed
from src.models import Document
from src.store import EmbeddingStore
from src.agent import KnowledgeBaseAgent


# ─────────────────────────────────────────────
# 1. TÀI LIỆU & METADATA
# ─────────────────────────────────────────────

HANDBOOK_DIR = project_root / "data" / "handbook"

DOCUMENTS_META = [
    {"file": "bat_dau_lam_viec.md",        "category": "onboarding", "topic": "first_days"},
    {"file": "cach_lam_viec.md",           "category": "work_culture", "topic": "remote_async"},
    {"file": "he_thong_noi_bo.md",         "category": "tools", "topic": "internal_systems"},
    {"file": "lam_them_ngoai_gio.md",      "category": "policy", "topic": "moonlighting"},
    {"file": "nghi_le_va_truyen_thong.md", "category": "culture", "topic": "traditions"},
    {"file": "nghi_viec_va_tro_cap.md",    "category": "policy", "topic": "severance"},
    {"file": "phat_trien_nghe_nghiep.md",  "category": "career", "topic": "promotion"},
    {"file": "phuc_loi_va_quyen_loi.md",   "category": "benefits", "topic": "insurance_pto"},
    {"file": "quan_ly_thiet_bi.md",        "category": "tools", "topic": "device_security"},
]

# ─────────────────────────────────────────────
# 2. BENCHMARK QUERIES (nhóm thống nhất)
# ─────────────────────────────────────────────

BENCHMARK_QUERIES = [
    {
        "id": 1,
        "query": "Nhân viên được nghỉ phép bao nhiêu ngày mỗi năm?",
        "gold_answer": "20 ngày nghỉ phép + 11 ngày lễ/năm. Tích lũy tối đa 27 ngày. Mùa hè làm 4 ngày/tuần (1/5–31/8). Sabbatical 6 tuần mỗi 3 năm.",
        "expected_doc": "phuc_loi_va_quyen_loi.md",
        "metadata_filter": None,
    },
    {
        "id": 2,
        "query": "Công ty có chính sách gì về làm thêm ngoài giờ?",
        "gold_answer": "Được phép: việc phụ cho bạn bè, diễn thuyết thỉnh thoảng, kinh doanh phụ vài giờ/tuần, cố vấn, tình nguyện. Không được: làm toàn/bán thời gian cho đối thủ, diễn thuyết thường xuyên, tư vấn đối thủ.",
        "expected_doc": "lam_them_ngoai_gio.md",
        "metadata_filter": None,
    },
    {
        "id": 3,
        "query": "Nhân viên mới cần gặp ai trong tuần đầu tiên?",
        "gold_answer": "Quản lý (1:1 ngày đầu), nhóm/team (cuộc gọi hàng tuần), Buddy 37signals (mentorship), và Nhân sự/People Ops (Andrea — chính sách & phúc lợi).",
        "expected_doc": "bat_dau_lam_viec.md",
        "metadata_filter": None,
    },
    {
        "id": 4,
        "query": "Mức lương tối thiểu và cách tính lương tại công ty?",
        "gold_answer": "Lương top 10% theo mức San Francisco (dữ liệu Radford). Lương tối thiểu $73,500. Cùng vai trò cùng cấp = cùng lương. Review mỗi năm vào tháng 11, tăng ngày 1/1 nếu cần. Không giảm lương.",
        "expected_doc": "phat_trien_nghe_nghiep.md",
        "metadata_filter": None,
    },
    {
        "id": 5,
        "query": "Công ty dùng hệ thống nào để theo dõi lỗi lập trình?",
        "gold_answer": "Sentry — theo dõi lỗi lập trình. Khi khách hàng gặp lỗi, Sentry ghi lại cho lập trình viên. Kiểm soát lỗi bởi SIP và Jim qua lịch trực.",
        "expected_doc": "he_thong_noi_bo.md",
        "metadata_filter": {"category": "tools"},
    },
]


def load_handbook_documents() -> list[Document]:
    """Load all handbook documents with metadata."""
    documents = []
    for meta in DOCUMENTS_META:
        filepath = HANDBOOK_DIR / meta["file"]
        if not filepath.exists():
            print(f"  ⚠ Missing: {filepath}")
            continue
        content = filepath.read_text(encoding="utf-8")
        documents.append(
            Document(
                id=filepath.stem,
                content=content,
                metadata={
                    "source": str(filepath.name),
                    "category": meta["category"],
                    "topic": meta["topic"],
                },
            )
        )
    return documents


def demo_llm(prompt: str) -> str:
    """Mock LLM — trả về một phần context để verify RAG pipeline."""
    # Tìm phần Answer: nếu có prompt format chuẩn
    if "Question:" in prompt:
        question_part = prompt.split("Question:")[-1].strip()
        context_preview = prompt[:600].replace("\n", " ")
        return f"[MOCK LLM] Dựa trên context đã retrieve, câu trả lời cho '{question_part.split(chr(10))[0]}': {context_preview[:300]}..."
    return f"[MOCK LLM] {prompt[:300]}..."


def run_baseline_comparison(documents: list[Document]) -> dict:
    """Run ChunkingStrategyComparator on 3 representative documents."""
    print("\n" + "=" * 70)
    print("PHẦN 1: BASELINE — ChunkingStrategyComparator")
    print("=" * 70)

    # 3 tài liệu đại diện: dài, trung bình, ngắn
    representative = ["phuc_loi_va_quyen_loi", "cach_lam_viec", "nghi_viec_va_tro_cap"]
    comparator = ChunkingStrategyComparator()
    all_results = {}

    for doc_id in representative:
        doc = next((d for d in documents if d.id == doc_id), None)
        if doc is None:
            continue
        results = comparator.compare(doc.content, chunk_size=200)
        all_results[doc_id] = results

        print(f"\n📄 {doc_id}.md ({len(doc.content)} chars)")
        print(f"  {'Strategy':<20} {'Chunk Count':>12} {'Avg Length':>12} {'Context?':>10}")
        print(f"  {'-'*54}")
        for strategy_name, stats in results.items():
            # Heuristic: check if chunks preserve context well
            preserve = "Yes" if stats["avg_length"] > 80 else "Partial"
            print(f"  {strategy_name:<20} {stats['count']:>12} {stats['avg_length']:>12.1f} {preserve:>10}")

    return all_results


def run_benchmark_queries(documents: list[Document], chunker_name: str = "RecursiveChunker") -> list[dict]:
    """Chunk documents, add to store, and run 5 benchmark queries."""
    print("\n" + "=" * 70)
    print(f"PHẦN 2: BENCHMARK QUERIES — Strategy: {chunker_name}")
    print("=" * 70)

    # Chunk each document
    chunker = RecursiveChunker(chunk_size=200)
    chunked_docs = []
    total_chunks = 0

    for doc in documents:
        chunks = chunker.chunk(doc.content)
        total_chunks += len(chunks)
        for i, chunk_text in enumerate(chunks):
            chunked_docs.append(
                Document(
                    id=f"{doc.id}_chunk_{i}",
                    content=chunk_text,
                    metadata={
                        **doc.metadata,
                        "chunk_index": str(i),
                    },
                )
            )

    print(f"\n✅ Loaded {len(documents)} documents → {total_chunks} chunks (RecursiveChunker, chunk_size=200)")

    # Create store and add chunked documents
    store = EmbeddingStore(collection_name="handbook_benchmark", embedding_fn=_mock_embed)
    store.add_documents(chunked_docs)
    print(f"✅ EmbeddingStore size: {store.get_collection_size()}")

    # Create agent
    agent = KnowledgeBaseAgent(store=store, llm_fn=demo_llm)

    # Run queries
    results = []
    print(f"\n{'─' * 70}")
    for bq in BENCHMARK_QUERIES:
        print(f"\n🔍 Query {bq['id']}: {bq['query']}")
        print(f"   Gold: {bq['gold_answer'][:100]}...")
        print(f"   Expected doc: {bq['expected_doc']}")

        # Search (with or without metadata filter)
        if bq["metadata_filter"]:
            print(f"   Metadata filter: {bq['metadata_filter']}")
            search_results = store.search_with_filter(
                bq["query"], top_k=3, metadata_filter=bq["metadata_filter"]
            )
            # search_with_filter uses 'content' or 'text' key depending on backend
            for r in search_results:
                if "text" in r and "content" not in r:
                    r["content"] = r["text"]
        else:
            search_results = store.search(bq["query"], top_k=3)

        # Display top-3
        print(f"\n   Top-3 Retrieved Chunks:")
        top1_content = ""
        top1_score = 0.0
        top1_relevant = False

        for rank, result in enumerate(search_results, 1):
            content_preview = result.get("content", result.get("text", ""))[:120].replace("\n", " ")
            score = result.get("score", 0.0)
            source = result.get("metadata", {}).get("source", "?")
            is_relevant = bq["expected_doc"] in source

            if rank == 1:
                top1_content = content_preview
                top1_score = score
                top1_relevant = is_relevant

            marker = "✅" if is_relevant else "❌"
            print(f"   {rank}. {marker} score={score:.4f} source={source}")
            print(f"      {content_preview}...")

        # Agent answer
        agent_answer = agent.answer(bq["query"], top_k=3)
        print(f"\n   🤖 Agent answer: {agent_answer[:200]}...")

        # Check if any top-3 result is from expected document
        any_relevant = any(
            bq["expected_doc"] in r.get("metadata", {}).get("source", "")
            for r in search_results
        )

        results.append({
            "id": bq["id"],
            "query": bq["query"],
            "top1_content": top1_content,
            "top1_score": top1_score,
            "top1_relevant": top1_relevant,
            "any_top3_relevant": any_relevant,
            "agent_answer": agent_answer[:200],
        })

    # Summary
    relevant_count = sum(1 for r in results if r["any_top3_relevant"])
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {relevant_count}/5 queries có chunk relevant trong top-3")
    print(f"{'=' * 70}")

    return results


def main() -> int:
    print("🚀 Group Benchmark — Lab 7: Embedding & Vector Store")
    print(f"   Domain: Employee Handbook (37signals)")
    print(f"   Handbook dir: {HANDBOOK_DIR}")

    # Load documents
    documents = load_handbook_documents()
    print(f"\n📚 Loaded {len(documents)} documents:")
    for doc in documents:
        print(f"   - {doc.id} ({len(doc.content)} chars) "
              f"| category={doc.metadata['category']}, topic={doc.metadata['topic']}")

    # Part 1: Baseline comparison
    baseline_results = run_baseline_comparison(documents)

    # Part 2: Benchmark queries
    benchmark_results = run_benchmark_queries(documents)

    # Print markdown table for report
    print(f"\n{'=' * 70}")
    print("MARKDOWN TABLE CHO REPORT (copy vào Section 6)")
    print(f"{'=' * 70}")
    print("\n| # | Query | Top-1 Retrieved Chunk (tóm tắt) | Score | Relevant? | Agent Answer (tóm tắt) |")
    print("|---|-------|--------------------------------|-------|-----------|------------------------|")
    for r in benchmark_results:
        relevant = "Yes ✅" if r["top1_relevant"] else "No ❌"
        print(f"| {r['id']} | {r['query'][:40]}... | {r['top1_content'][:50]}... | {r['top1_score']:.4f} | {relevant} | {r['agent_answer'][:50]}... |")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
