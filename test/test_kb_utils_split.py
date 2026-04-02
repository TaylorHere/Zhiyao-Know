from src.knowledge.utils.kb_utils import split_text_into_chunks


def test_split_text_into_chunks_separator_as_chunk() -> None:
    text = (
        "# A\n"
        "## 标准检索单元\n"
        "- 编号: 1\n"
        "---\n"
        "## 标准检索单元\n"
        "- 编号: 2\n"
        "---\n"
        "## 标准检索单元\n"
        "- 编号: 3\n"
    )
    params = {
        "chunk_size": 10,
        "chunk_overlap": 2,
        "qa_separator": "\n---\n",
        "separator_as_chunk": True,
    }
    chunks = split_text_into_chunks(text, "file_x", "x.md", params)
    assert len(chunks) == 3
    assert all("## 标准检索单元" in c["content"] for c in chunks)
