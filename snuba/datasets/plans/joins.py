import itertools

from typing import Sequence

from snuba.datasets.plans.query_plan import (
    StorageQueryPlan,
    StorageQueryPlanBuilder,
)
from snuba.datasets.schemas.join import JoinClause
from snuba.datasets.storage import TableStorage
from snuba.datasets.plans.single_table import SimpleQueryPlanExecutionStrategy
from snuba.query.query_processor import QueryProcessor
from snuba.request import Request


class JoinQueryPlanBuilder(StorageQueryPlanBuilder):
    """
    Builds the Storage Query Execution plan for a Join dataset.
    """

    def __init__(
        self,
        storages: Sequence[TableStorage],
        join_spec: JoinClause,
        post_processors: Sequence[QueryProcessor],
    ) -> None:
        self.__storages = storages
        self.__join_spec = join_spec
        self.__post_processors = post_processors

    def build_plan(self, request: Request) -> StorageQueryPlan:
        request.query.set_data_source(self.__join_spec)
        processors = itertools.chain.from_iterable(
            storage.get_query_processors() for storage in self.__storages
        )

        return StorageQueryPlan(
            query_processors=processors + self.__post_processors,
            execution_strategy=SimpleQueryPlanExecutionStrategy(),
        )