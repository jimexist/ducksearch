import collections
import logging
import os

import pyarrow as pa
import pyarrow.parquet as pq
from joblib import Parallel, delayed

from ..decorators import execute_with_duckdb
from ..utils import batchify
from .create import _select_settings


@execute_with_duckdb(
    relative_path="search/create/queries_index.sql",
)
def _create_queries_index() -> None:
    """Index the queries."""


@execute_with_duckdb(
    relative_path="search/insert/queries.sql",
)
def _insert_queries() -> None:
    """Index the queries."""


@execute_with_duckdb(
    relative_path="search/select/search.sql",
    read_only=True,
    fetch_df=True,
)
def _search_query():
    """Search in duckdb."""


@execute_with_duckdb(
    relative_path="search/select/search_filters.sql",
    read_only=True,
    fetch_df=True,
)
def _search_query_filters():
    """Search in duckdb."""


def documents(
    database: str,
    queries: str | list[str],
    batch_size: int = 30,
    top_k: int = 10,
    top_k_token: int = 10_000,
    n_jobs: int = -1,
    config: dict | None = None,
    filters: str | None = None,
    **kwargs,
) -> list[list[dict]]:
    """Search for documents from the documents table.

    Parameters
    ----------
    database
        The name of the DuckDB database.
    queries
        The list of queries to search.
    ngram_range
        The ngram range to use.
    analyzer
        The analyzer to use. Either "word" or "char" or "char_wb".
    normalize
        Normalize the text.
    batch_size
        The batch size to use.
    top_k
        The number of top documents to retrieve.
    top_k_token
        The number of top tokens to retrieve. It will be used to select top k documents per
        token.
    n_jobs
        The number of parallel jobs to run. -1 means using all processors.
    config
        The configuration options for the DuckDB connection

    Examples
    --------
    >>> from ducksearch import evaluation, upload, search

    >>> documents, queries, qrels = evaluation.load_beir(
    ...     "scifact",
    ...     split="test"
    ... )

    >>> scores = search.documents(
    ...     database="test.duckdb",
    ...     queries=queries,
    ...     top_k_token=1000,
    ... )

    >>> evaluation_scores = evaluation.evaluate(
    ...     scores=scores,
    ...     qrels=qrels,
    ...     queries=queries,
    ...     metrics=["ndcg@10", "hits@1", "hits@2", "hits@3", "hits@4", "hits@5", "hits@10"],
    ... )

    >>> assert evaluation_scores["ndcg@10"] > 0.68

    >>> for sample_documents in scores:
    ...     for document in sample_documents:
    ...         assert "title" in document
    ...         assert "text" in document
    ...         assert "score" in document
    ...         assert "id" in document

    >>> scores = search.documents(
    ...     database="test.duckdb",
    ...     queries=queries,
    ...     filters="id = '11360768' OR id = '11360768'",
    ... )

    >>> for sample in scores:
    ...   for document in sample:
    ...     assert document["id"] == "11360768" or document["id"] == "11360768"

    """
    return search(
        database=database,
        schema="bm25_documents",
        source_schema="bm25_tables",
        source="documents",
        queries=queries,
        config=config,
        batch_size=batch_size,
        top_k=top_k,
        top_k_token=top_k_token,
        n_jobs=n_jobs,
        filters=filters,
    )


def queries(
    database: str,
    queries: str | list[str],
    batch_size: int = 30,
    top_k: int = 10,
    top_k_token: int = 10_000,
    n_jobs: int = -1,
    config: dict | None = None,
    filters: str | None = None,
    **kwargs,
) -> list[list[dict]]:
    """Search for queries from the queries table.

    Parameters
    ----------
    database
        The name of the DuckDB database.
    queries
        The list of queries to search.
    ngram_range
        The ngram range to use.
    analyzer
        The analyzer to use. Either "word" or "char" or "char_wb".
    normalize
        Normalize the text.
    batch_size
        The batch size to use.
    top_k
        The number of top documents to retrieve.
    top_k_token
        The number of top tokens to retrieve. It will be used to select top k documents per
        token.
    n_jobs
        The number of parallel jobs to run. -1 means using all processors.
    config
        The configuration options for the DuckDB connection

    Examples
    --------
    >>> from ducksearch import evaluation, upload, search

    >>> documents, queries, qrels = evaluation.load_beir(
    ...     "scifact",
    ...     split="test"
    ... )

    >>> scores = search.queries(
    ...     database="test.duckdb",
    ...     queries=queries,
    ... )

    >>> n = 0
    >>> for sample, query in zip(scores, queries):
    ...   if sample[0]["query"] == query:
    ...     n += 1

    >>> assert n >= 290

    >>> scores = search.queries(
    ...     database="test.duckdb",
    ...     queries=queries,
    ...     filters="id = 1 OR id = 2",
    ... )

    >>> for sample in scores:
    ...   for document in sample:
    ...     assert document["id"] == "1" or document["id"] == "2"

    """
    return search(
        database=database,
        schema="bm25_queries",
        source_schema="bm25_tables",
        source="queries",
        queries=queries,
        config=config,
        batch_size=batch_size,
        top_k=top_k,
        top_k_token=top_k_token,
        n_jobs=n_jobs,
        filters=filters,
    )


def _search(
    database: str,
    schema: str,
    source_schema: str,
    source: str,
    queries: list[str],
    top_k: int,
    top_k_token: int,
    index: int,
    config: dict | None = None,
    filters: str | None = None,
) -> list:
    """Search in duckdb.

    Parameters
    ----------
    queries
        The list of queries to search.
    top_k
        The number of top documents to retrieve.
    top_k_token
        The number of top tokens to retrieve. It will be used to select top k documents per
        token.
    index
        The index of the batch.

    """
    search_function = _search_query_filters if filters is not None else _search_query

    index_table = pa.Table.from_pydict(
        {
            "query": queries,
        }
    )

    pq.write_table(
        index_table,
        f"_queries_{index}.parquet",
        compression="snappy",
    )

    matchs = search_function(
        database=database,
        schema=schema,
        source_schema=source_schema,
        source=source,
        top_k=top_k,
        top_k_token=top_k_token,
        parquet_file=f"_queries_{index}.parquet",
        filters=filters,
        config=config,
    )

    if os.path.exists(f"_queries_{index}.parquet"):
        os.remove(f"_queries_{index}.parquet")

    candidates = collections.defaultdict(list)
    for match in matchs:
        query = match.pop("_query")
        candidates[query].append(match)
    return [candidates[query] for query in queries]


def search(
    database: str,
    schema: str,
    source_schema: str,
    source: str,
    queries: str | list[str],
    batch_size: int = 30,
    top_k: int = 10,
    top_k_token: int = 10_000,
    n_jobs: int = -1,
    config: dict | None = None,
    filters: str | None = None,
) -> None:
    """Run the search in parallel.

    Parameters
    ----------
    database
        The name of the DuckDB database.
    schema
        The name of the schema to search.
    queries
        The list of queries to search.
    ngram_range
        The ngram range to use.
    analyzer
        The analyzer to use. Either "word" or "char" or "char_wb".
    normalize
        Normalize the text.
    batch_size
        The batch size to use.
    top_k
        The number of top documents to retrieve.
    top_k_token
        The number of top tokens to retrieve. It will be used to select top k documents per
        token.
    n_jobs
        The number of parallel jobs to run. -1 means using all processors.
    config
        The configuration options for the DuckDB connection

    Examples
    --------
    >>> from ducksearch import search

    >>> documents = search.search(
    ...     database="test.duckdb",
    ...     source_schema="bm25_tables",
    ...     schema="bm25_documents",
    ...     source="documents",
    ...     queries="random query",
    ...     top_k_token=10_000,
    ...     top_k=10,
    ... )

    assert len(documents) == 1
    assert len(documents[0]) == 10


    """
    if isinstance(queries, str):
        queries = [queries]

    logging.info("Indexing queries.")
    index_table = pa.Table.from_pydict(
        {
            "query": queries,
        }
    )

    settings = _select_settings(
        database=database,
        schema=schema,
        config=config,
    )[0]

    pq.write_table(
        index_table,
        "_queries.parquet",
        compression="snappy",
    )

    _insert_queries(
        database=database,
        schema=schema,
        parquet_file="_queries.parquet",
        config=config,
    )

    _create_queries_index(
        database=database,
        schema=schema,
        **settings,
        config=config,
    )

    matchs = []
    for match in Parallel(
        n_jobs=1 if len(queries) <= batch_size else n_jobs, backend="threading"
    )(
        delayed(function=_search)(
            database,
            schema,
            source_schema,
            source,
            batch_queries,
            top_k,
            top_k_token,
            index,
            config,
            filters=filters,
        )
        for index, batch_queries in enumerate(
            iterable=batchify(X=queries, batch_size=batch_size, desc="Searching")
        )
    ):
        matchs.extend(match)

    return matchs
