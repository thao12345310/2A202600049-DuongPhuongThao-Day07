#!/usr/bin/env python3
"""
Group Benchmark V3 — Local Embedder (all-MiniLM-L6-v2)
=======================================================
Chạy: python3 scripts/run_group_benchmark_v3.py

So sánh TOÀN DIỆN 3 phiên bản:
  V1: RecursiveChunker + mock embedder + 1 filter
  V2: SectionChunker  + mock embedder + all filters
  V3: SectionChunker  + LOCAL embedder + NO filters (pure semantic search)
  V3b: SectionChunker + LOCAL embedder + all filters (best of both)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.chunking import SectionChunker, RecursiveChunker
from src.embeddings import LocalEmbedder, _mock_embed
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
        "gold_answer": "Được phép: việc phụ cho bạn bè, diễn thuyết thỉnh thoảng. Không được: làm toàn/bán thời gian cho đối thủ.",
        "expected_doc": "lam_them_ngoai_gio.md",
        "metadata_filter": {"category": "policy"},
    },
    {
        "id": 3,
        "query": "Nhân viên mới cần gặp ai trong tuần đầu tiên?",
        "gold_answer": "Quản lý, nhóm/team, Buddy 37signals, Nhân sự/People Ops (Andrea).",
        "expected_doc": "bat_dau_lam_viec.md",
        "metadata_filter": {"category": "onboarding"},
    },
    {
        "id": 4,
        "query": "Mức lương tối thiểu và cách tính lương tại công ty?",
        "gold_answer": "Lương top 10% theo mức SF (Radford). Tối thiểu $73,500. Cùng vai trò cùng cấp = cùng lương.",
        "expected_doc": "phat_trien_nghe_nghiep.md",
        "metadata_filter": {"category": "career"},
    },
    {
        "id": 5,
        "query": "Công ty dùng hệ thống nào để theo dõi lỗi lập trình?",
        "gold_answer": "Sentry — theo dõi lỗi lập trình. Kiểm soát bởi SIP và Jim qua lịch trực.",
        "expected_doc": "he_thong_noi_bo.md",
        "metadata_filter": {"category": "tools"},
    },
]


def load_handbook_documents() -> list[Document]:
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
    if "Question:" in prompt:
        question_part = prompt.split("Question:")[-1].strip().split("\n")[0]
        context = prompt.split("Context:")[1].split("Question:")[0] if "Context:" in prompt else ""
        return f"[MOCK LLM] Trả lời cho '{question_part}' dựa trên: {context[:300].replace(chr(10), ' ')}..."
    return f"[MOCK LLM] {prompt[:300]}..."


def chunk_documents(documents: list[Document], chunker, chunker_name: str) -> list[Document]:
    chunked_docs = []
    total = 0
    for doc in documents:
        chunks = chunker.chunk(doc.content)
        total += len(chunks)
        for i, chunk_text in enumerate(chunks):
            chunked_docs.append(
                Document(
                    id=f"{doc.id}_{chunker_name}_{i}",
                    content=chunk_text,
                    metadata={**doc.metadata, "chunk_index": str(i)},
                )
            )
    print(f"  → {len(documents)} docs → {total} chunks ({chunker_name})")
    return chunked_docs


def run_benchmark(
    label: str,
    chunked_docs: list[Document],
    embedder,
    use_filter: bool,
) -> list[dict]:
    """Run 5 benchmark queries and return results."""
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")

    store = EmbeddingStore(collection_name=f"bench_{label.replace(' ', '_')}", embedding_fn=embedder)
    store.add_documents(chunked_docs)
    print(f"  Store size: {store.get_collection_size()}")
    embedder_name = getattr(embedder, '_backend_name', 'mock')
    print(f"  Embedder: {embedder_name}")
    print(f"  Metadata filter: {'ALL queries' if use_filter else 'NONE (pure semantic)'}")

    agent = KnowledgeBaseAgent(store=store, llm_fn=demo_llm)
    results = []

    for bq in BENCHMARK_QUERIES:
        # Decide search method
        if use_filter and bq["metadata_filter"]:
            search_results = store.search_with_filter(
                bq["query"], top_k=3, metadata_filter=bq["metadata_filter"]
            )
            for r in search_results:
                if "text" in r and "content" not in r:
                    r["content"] = r["text"]
        else:
            search_results = store.search(bq["query"], top_k=3)

        # Check relevance
        top1_relevant = False
        top1_score = 0.0
        top1_content = ""
        top1_source = ""

        for rank, result in enumerate(search_results, 1):
            source = result.get("metadata", {}).get("source", "?")
            score = result.get("score", 0.0)

            if rank == 1:
                top1_source = source
                top1_score = score
                top1_content = result.get("content", "")[:100].replace("\n", " ")
                top1_relevant = bq["expected_doc"] in source

        any_relevant = any(
            bq["expected_doc"] in r.get("metadata", {}).get("source", "")
            for r in search_results
        )

        # Agent answer
        agent_answer = agent.answer(bq["query"], top_k=3)

        results.append({
            "id": bq["id"],
            "query": bq["query"],
            "top1_source": top1_source,
            "top1_score": top1_score,
            "top1_content": top1_content,
            "top1_relevant": top1_relevant,
            "any_top3_relevant": any_relevant,
            "agent_answer": agent_answer[:200],
        })

        marker_1 = "✅" if top1_relevant else "❌"
        marker_3 = "✅" if any_relevant else "❌"
        print(f"  Q{bq['id']}: top1={marker_1} top3={marker_3} score={top1_score:.4f} → {top1_source}")

    r_count = sum(1 for r in results if r["any_top3_relevant"])
    r1_count = sum(1 for r in results if r["top1_relevant"])
    print(f"\n  📊 Top-1 relevant: {r1_count}/5 | Top-3 relevant: {r_count}/5")

    return results


def main() -> int:
    print("🚀 Group Benchmark V3 — Local Embedder (all-MiniLM-L6-v2)")
    print("=" * 70)

    # Load documents
    documents = load_handbook_documents()
    print(f"\n📚 Loaded {len(documents)} documents")

    # Initialize embedders
    print("\n🔧 Initializing LocalEmbedder (all-MiniLM-L6-v2)...")
    try:
        local_embedder = LocalEmbedder()
        print(f"  ✅ Backend: {local_embedder._backend_name}")
        test_vec = local_embedder("test")
        print(f"  ✅ Vector dim: {len(test_vec)}")
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return 1

    # Prepare chunked documents
    print("\n📝 Chunking documents...")
    section_chunker = SectionChunker(max_section_chars=1000)
    recursive_chunker = RecursiveChunker(chunk_size=200)

    section_chunks = chunk_documents(documents, section_chunker, "section")
    recursive_chunks = chunk_documents(documents, recursive_chunker, "recursive")

    # ─── Run 4 benchmark configurations ───
    # V1: RecursiveChunker + mock + 1 filter → already known: 1/5
    # V2: SectionChunker  + mock + all filters → already known: 5/5

    # V3: SectionChunker + LOCAL + NO filter (pure semantic search)
    v3_results = run_benchmark(
        "V3: SectionChunker + LocalEmbedder (NO filter)",
        section_chunks, local_embedder, use_filter=False,
    )

    # V3b: SectionChunker + LOCAL + all filters (best combo)
    v3b_results = run_benchmark(
        "V3b: SectionChunker + LocalEmbedder + ALL filters",
        section_chunks, local_embedder, use_filter=True,
    )

    # V3c: RecursiveChunker + LOCAL + NO filter
    v3c_results = run_benchmark(
        "V3c: RecursiveChunker + LocalEmbedder (NO filter)",
        recursive_chunks, local_embedder, use_filter=False,
    )

    # Final comparison
    print(f"\n{'=' * 70}")
    print("📊 TỔNG KẾT SO SÁNH TẤT CẢ VERSIONS")
    print(f"{'=' * 70}")
    print(f"\n{'Version':<55} {'Top-1':>7} {'Top-3':>7}")
    print(f"{'-' * 70}")
    print(f"{'V1: RecursiveChunker + MockEmbed + 1 filter':<55} {'0/5':>7} {'1/5':>7}")
    print(f"{'V2: SectionChunker  + MockEmbed + all filters':<55} {'4/5':>7} {'5/5':>7}")

    v3_top1 = sum(1 for r in v3_results if r["top1_relevant"])
    v3_top3 = sum(1 for r in v3_results if r["any_top3_relevant"])
    print(f"{'V3: SectionChunker  + LocalEmbed + NO filter':<55} {f'{v3_top1}/5':>7} {f'{v3_top3}/5':>7}")

    v3b_top1 = sum(1 for r in v3b_results if r["top1_relevant"])
    v3b_top3 = sum(1 for r in v3b_results if r["any_top3_relevant"])
    print(f"{'V3b: SectionChunker + LocalEmbed + ALL filters':<55} {f'{v3b_top1}/5':>7} {f'{v3b_top3}/5':>7}")

    v3c_top1 = sum(1 for r in v3c_results if r["top1_relevant"])
    v3c_top3 = sum(1 for r in v3c_results if r["any_top3_relevant"])
    print(f"{'V3c: RecursiveChunker + LocalEmbed + NO filter':<55} {f'{v3c_top1}/5':>7} {f'{v3c_top3}/5':>7}")

    # Best configuration
    best = max(
        [("V3", v3_top1, v3_top3), ("V3b", v3b_top1, v3b_top3), ("V3c", v3c_top1, v3c_top3)],
        key=lambda x: (x[2], x[1])
    )
    print(f"\n🏆 Best: {best[0]} (Top-1: {best[1]}/5, Top-3: {best[2]}/5)")

    # Detailed results for V3 (pure semantic, no filter)
    print(f"\n{'=' * 70}")
    print("CHI TIẾT V3: SectionChunker + LocalEmbedder (NO filter)")
    print(f"{'=' * 70}")
    print("\n| # | Query | Top-1 Source | Score | Top-1? | Top-3? |")
    print("|---|-------|-------------|-------|--------|--------|")
    for r in v3_results:
        t1 = "✅" if r["top1_relevant"] else "❌"
        t3 = "✅" if r["any_top3_relevant"] else "❌"
        print(f"| {r['id']} | {r['query'][:40]}... | {r['top1_source']} | {r['top1_score']:.4f} | {t1} | {t3} |")

    # Detailed results for V3b (semantic + filter)
    print(f"\n{'=' * 70}")
    print("CHI TIẾT V3b: SectionChunker + LocalEmbedder + ALL filters")
    print(f"{'=' * 70}")
    print("\n| # | Query | Top-1 Source | Score | Top-1? | Top-3? |")
    print("|---|-------|-------------|-------|--------|--------|")
    for r in v3b_results:
        t1 = "✅" if r["top1_relevant"] else "❌"
        t3 = "✅" if r["any_top3_relevant"] else "❌"
        print(f"| {r['id']} | {r['query'][:40]}... | {r['top1_source']} | {r['top1_score']:.4f} | {t1} | {t3} |")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
