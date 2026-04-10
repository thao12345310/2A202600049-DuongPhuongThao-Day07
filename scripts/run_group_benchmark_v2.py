#!/usr/bin/env python3
"""
Group Benchmark V2 — Improved Strategy: SectionChunker + Metadata Filtering
============================================================================
Chạy: python3 scripts/run_group_benchmark_v2.py

Cải tiến so với V1 (RecursiveChunker, chỉ filter query #5):
1. SectionChunker: chunk theo markdown headers → mỗi chunk = 1 section trọn vẹn
2. Metadata filtering cho TẤT CẢ 5 queries → thu hẹp search space
3. So sánh kết quả V1 vs V2
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.chunking import SectionChunker, RecursiveChunker, ChunkingStrategyComparator
from src.embeddings import _mock_embed
from src.models import Document
from src.store import EmbeddingStore
from src.agent import KnowledgeBaseAgent

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

# V2: Metadata filtering cho TẤT CẢ queries
BENCHMARK_QUERIES = [
    {
        "id": 1,
        "query": "Nhân viên được nghỉ phép bao nhiêu ngày mỗi năm?",
        "gold_answer": "20 ngày nghỉ phép + 11 ngày lễ/năm. Tích lũy tối đa 27 ngày. Mùa hè làm 4 ngày/tuần (1/5–31/8). Sabbatical 6 tuần mỗi 3 năm.",
        "expected_doc": "phuc_loi_va_quyen_loi.md",
        "metadata_filter": {"category": "benefits"},
    },
    {
        "id": 2,
        "query": "Công ty có chính sách gì về làm thêm ngoài giờ?",
        "gold_answer": "Được phép: việc phụ cho bạn bè, diễn thuyết thỉnh thoảng, kinh doanh phụ vài giờ/tuần. Không được: làm toàn/bán thời gian cho đối thủ.",
        "expected_doc": "lam_them_ngoai_gio.md",
        "metadata_filter": {"category": "policy"},
    },
    {
        "id": 3,
        "query": "Nhân viên mới cần gặp ai trong tuần đầu tiên?",
        "gold_answer": "Quản lý (1:1 ngày đầu), nhóm/team (cuộc gọi hàng tuần), Buddy 37signals (mentorship), Nhân sự/People Ops (Andrea).",
        "expected_doc": "bat_dau_lam_viec.md",
        "metadata_filter": {"category": "onboarding"},
    },
    {
        "id": 4,
        "query": "Mức lương tối thiểu và cách tính lương tại công ty?",
        "gold_answer": "Lương top 10% theo mức San Francisco (dữ liệu Radford). Tối thiểu $73,500. Cùng vai trò cùng cấp = cùng lương.",
        "expected_doc": "phat_trien_nghe_nghiep.md",
        "metadata_filter": {"category": "career"},
    },
    {
        "id": 5,
        "query": "Công ty dùng hệ thống nào để theo dõi lỗi lập trình?",
        "gold_answer": "Sentry — theo dõi lỗi lập trình. Khi khách hàng gặp lỗi, Sentry ghi lại.",
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
    """Mock LLM."""
    if "Question:" in prompt:
        question_part = prompt.split("Question:")[-1].strip()
        context_preview = prompt[:800].replace("\n", " ")
        return f"[MOCK LLM] Dựa trên context: {context_preview[:400]}..."
    return f"[MOCK LLM] {prompt[:300]}..."


def run_section_chunker_analysis(documents: list[Document]):
    """Show SectionChunker stats vs RecursiveChunker."""
    print("\n" + "=" * 70)
    print("PHẦN 1: SECTION CHUNKER vs RECURSIVE CHUNKER")
    print("=" * 70)

    section_chunker = SectionChunker(max_section_chars=1000)
    recursive_chunker = RecursiveChunker(chunk_size=200)

    representative = ["phuc_loi_va_quyen_loi", "cach_lam_viec", "bat_dau_lam_viec"]

    for doc_id in representative:
        doc = next((d for d in documents if d.id == doc_id), None)
        if not doc:
            continue

        section_chunks = section_chunker.chunk(doc.content)
        recursive_chunks = recursive_chunker.chunk(doc.content)

        print(f"\n📄 {doc_id}.md ({len(doc.content)} chars)")
        print(f"  {'Strategy':<25} {'Chunks':>8} {'Avg Len':>10} {'Max Len':>10}")
        print(f"  {'-' * 55}")

        s_avg = sum(len(c) for c in section_chunks) / len(section_chunks) if section_chunks else 0
        s_max = max(len(c) for c in section_chunks) if section_chunks else 0
        r_avg = sum(len(c) for c in recursive_chunks) / len(recursive_chunks) if recursive_chunks else 0
        r_max = max(len(c) for c in recursive_chunks) if recursive_chunks else 0

        print(f"  {'SectionChunker (1000)':<25} {len(section_chunks):>8} {s_avg:>10.1f} {s_max:>10}")
        print(f"  {'RecursiveChunker (200)':<25} {len(recursive_chunks):>8} {r_avg:>10.1f} {r_max:>10}")

        # Show section chunks preview
        print(f"\n  Section chunks preview:")
        for i, chunk in enumerate(section_chunks):
            first_line = chunk.split("\n")[0][:80]
            print(f"    [{i}] ({len(chunk)} chars) {first_line}")


def run_benchmark_v2(documents: list[Document]) -> list[dict]:
    """Run benchmark with SectionChunker + metadata filtering on all queries."""
    print("\n" + "=" * 70)
    print("PHẦN 2: BENCHMARK V2 — SectionChunker + Full Metadata Filtering")
    print("=" * 70)

    chunker = SectionChunker(max_section_chars=1000)
    chunked_docs = []
    total_chunks = 0

    for doc in documents:
        chunks = chunker.chunk(doc.content)
        total_chunks += len(chunks)
        for i, chunk_text in enumerate(chunks):
            chunked_docs.append(
                Document(
                    id=f"{doc.id}_sec_{i}",
                    content=chunk_text,
                    metadata={**doc.metadata, "chunk_index": str(i)},
                )
            )

    print(f"\n✅ {len(documents)} documents → {total_chunks} chunks (SectionChunker, max=1000)")

    store = EmbeddingStore(collection_name="handbook_v2", embedding_fn=_mock_embed)
    store.add_documents(chunked_docs)
    print(f"✅ EmbeddingStore size: {store.get_collection_size()}")

    agent = KnowledgeBaseAgent(store=store, llm_fn=demo_llm)

    results = []
    print(f"\n{'─' * 70}")

    for bq in BENCHMARK_QUERIES:
        print(f"\n🔍 Query {bq['id']}: {bq['query']}")
        print(f"   Gold: {bq['gold_answer'][:80]}...")
        print(f"   Expected: {bq['expected_doc']}")
        print(f"   Filter: {bq['metadata_filter']}")

        # ALL queries use metadata filtering in V2
        search_results = store.search_with_filter(
            bq["query"], top_k=3, metadata_filter=bq["metadata_filter"]
        )
        # Normalize key names
        for r in search_results:
            if "text" in r and "content" not in r:
                r["content"] = r["text"]

        print(f"\n   Top-3 Retrieved Chunks:")
        top1_content = ""
        top1_score = 0.0
        top1_relevant = False

        for rank, result in enumerate(search_results, 1):
            content_preview = result.get("content", "")[:120].replace("\n", " ")
            score = result.get("score", 0.0)
            source = result.get("metadata", {}).get("source", "?")
            is_relevant = bq["expected_doc"] in source

            if rank == 1:
                top1_content = content_preview
                top1_score = score
                top1_relevant = is_relevant

            marker = "✅" if is_relevant else "❌"
            print(f"   {rank}. {marker} score={score:.4f} source={source}")
            print(f"      {content_preview[:100]}...")

        # Agent answer
        agent_answer = agent.answer(bq["query"], top_k=3)
        print(f"\n   🤖 Agent: {agent_answer[:150]}...")

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

    relevant_count = sum(1 for r in results if r["any_top3_relevant"])
    print(f"\n{'=' * 70}")
    print(f"SUMMARY V2: {relevant_count}/5 queries có chunk relevant trong top-3")
    print(f"{'=' * 70}")

    # Comparison table
    print(f"\n📊 SO SÁNH V1 vs V2:")
    print(f"  V1 (RecursiveChunker, 1 filter):  1/5 relevant")
    print(f"  V2 (SectionChunker, all filters): {relevant_count}/5 relevant")
    print(f"  Improvement: +{relevant_count - 1} queries")

    return results


def main() -> int:
    print("🚀 Group Benchmark V2 — SectionChunker + Full Metadata Filtering")
    print(f"   Domain: Employee Handbook (37signals)")

    documents = load_handbook_documents()
    print(f"\n📚 Loaded {len(documents)} documents")

    # Part 1: SectionChunker analysis
    run_section_chunker_analysis(documents)

    # Part 2: Benchmark with improved strategy
    results = run_benchmark_v2(documents)

    # Markdown output for report
    print(f"\n{'=' * 70}")
    print("MARKDOWN TABLE CHO REPORT")
    print(f"{'=' * 70}")
    print("\n| # | Query | Top-1 Chunk (tóm tắt) | Score | Relevant? |")
    print("|---|-------|-----------------------|-------|-----------|")
    for r in results:
        relevant = "Yes ✅" if r["top1_relevant"] else "No ❌"
        print(f"| {r['id']} | {r['query'][:45]}... | {r['top1_content'][:50]}... | {r['top1_score']:.4f} | {relevant} |")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
